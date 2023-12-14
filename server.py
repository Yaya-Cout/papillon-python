# importe les modules importants
from pyexpat.errors import messages
from os import environ
import hug
import pronotepy
import datetime
import time
import secrets
import falcon
import json
import socket
import base64
import sentry_sdk

import resource
resource.setrlimit(resource.RLIMIT_CORE, (resource.RLIM_INFINITY, resource.RLIM_INFINITY))

# importe les ENT
from pronotepy.ent import *

API_VERSION = open('VERSION', 'r').read().strip()
MAINTENANCE = json.load(open('maintenance.json', 'r', encoding='utf8'))
CAS_LIST = json.load(open('cas_list.json', 'r', encoding='utf8'))

sentry_sdk.init(
	dsn=environ['DSN_URL'],
	release=f'papillon-api@{API_VERSION}'
)

# ajouter les CORS sur toutes les routes
@hug.response_middleware()
def CORS(request, response, resource):
	response.set_header('Access-Control-Allow-Origin', '*')
	response.set_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
	response.set_header(
		'Access-Control-Allow-Headers',
		'Authorization,Keep-Alive,User-Agent,'
		'If-Modified-Since,Cache-Control,Content-Type'
	)
	response.set_header(
		'Access-Control-Expose-Headers',
		'Authorization,Keep-Alive,User-Agent,'
		'If-Modified-Since,Cache-Control,Content-Type'
	)
	if request.method == 'OPTIONS':
		response.set_header('Access-Control-Max-Age', 1728000)
		response.set_header('Content-Type', 'text/plain charset=UTF-8')
		response.set_header('Content-Length', 0)
		response.status_code = hug.HTTP_204

# système de tokens
saved_clients = {}
"""
saved_clients ->
	token ->
		client -> instance de pronotepy.Client
		last_interaction -> int (provenant de time.time(), entier représentant le temps depuis la dernière intéraction avec le client)
"""
client_timeout_threshold = 300 # le temps en sec avant qu'un jeton ne soit rendu invalide

def get_client(token: str) -> tuple[str, pronotepy.Client|None]:
	"""Retourne le client Pronote associé au jeton.

	Args:
		token (str): le jeton à partir duquel retrouver le client.
		instance (bool): si True, le client ne sera pas recherché sur les autres instances.

	Returns:
		tuple: le couple (statut, client?) associé au jeton
			str: le statut de la demande ('ok' si le client est trouvé, 'expired' si le jeton a expiré, 'notfound' si le jeton n'est pas associé à un client)
			pronotepy.Client|None: une instance de client si le token est valide, None sinon.

	"""
	if MAINTENANCE['enable']:
		return 'maintenance', None
	if token in saved_clients:
		client_dict = saved_clients[token]
		if time.time() - client_dict['last_interaction'] < client_timeout_threshold:
			client_dict['last_interaction'] = time.time()
			return 'ok', client_dict['client']
		else:
			del saved_clients[token]
			print(len(saved_clients), 'valid tokens')
			return 'expired', None
	else:
		return 'notfound', None

@hug.get('/infos')
def infos():
	return {
		'status': 'ok' if not MAINTENANCE['enable'] else 'maintenance',
		'message': 'server is running' if not MAINTENANCE['enable'] else MAINTENANCE['message'],
		'server': socket.gethostname(),
		'version': API_VERSION,
		'ent_list': CAS_LIST if not MAINTENANCE['enable'] else []
	}
 
# requête initiale :
# un client doit faire
# token = POST /generatetoken body={url, username, password, ent}
# GET * token=token
@hug.post('/generatetoken')
def generate_token(response, body=None, method: hug.types.one_of(['url', 'qrcode', 'token'])='url', type: hug.types.one_of(['eleve', 'parent'])='eleve', version: hug.types.one_of(['1', '2'])='1'):
	if MAINTENANCE['enable']:
		response.status = falcon.get_http_status(503)
		return {
			'token': False,
			'error': 'Maintenance'
		}

	if not body is None:
		noENT = False

		# version 2 uses base64
		if version == '2':
			try :
				body['url'] = base64.b64decode(body['url']).decode('utf-8')
				body['username'] = base64.b64decode(body['username']).decode('utf-8')
				body['password'] = base64.b64decode(body['password']).decode('utf-8')
				if 'ent' in body:
					body['ent'] = base64.b64decode(body['ent']).decode('utf-8')
			except Exception as e:
				response.status = falcon.get_http_status(400)
				return {
					"token": False,
					"error": f'Invalid base64'
				}

		if method == "url":
			for rk in ('url', 'username', 'password', 'ent'):
				if not rk in body and rk != 'ent':
					response.status = falcon.get_http_status(400)
					return {
						"token": False,
						"error": f'Missing {rk}'
					}
				elif not rk in body and rk == 'ent':
					noENT = True 

			try:
				if noENT:
					if type == 'parent':
						client = pronotepy.ParentClient(body['url'], username=body['username'], password=body['password'])
					else:
						client = pronotepy.Client(body['url'], username=body['username'], password=body['password'])
				else:
					if type == 'parent':
						client = pronotepy.ParentClient(body['url'], username=body['username'], password=body['password'], ent=getattr(pronotepy.ent, body['ent']))
					else:
						client = pronotepy.Client(body['url'], username=body['username'], password=body['password'], ent=getattr(pronotepy.ent, body['ent']))
			except Exception as e:
				response.status = falcon.get_http_status(498)
				print(f"Error while trying to connect to {body['url']}")
				print(e)

				error = {
					"token": False,
					"error": str(e),
				}
				return error

		elif method == "qrcode":
			for rk in ('url', 'qrToken', 'login', 'checkCode', 'uuid'):
				if not rk in body:
					response.status = falcon.get_http_status(400)
					return {
						"token": False,
						"error": f'Missing {rk}'
					}
				elif rk == "checkCode":
					if len(body["checkCode"]) != 4:
						response.status = falcon.get_http_status(400)
						return {
							"token": False,
							"error": f'checkCode must be 4 characters long (got {len(body["checkCode"])})'
						}

			try:
				client = pronotepy.Client.qrcode_login({
					"jeton": body['qrToken'],
					"login": body['login'],
					"url": body['url']
				}, body['checkCode'], body['uuid'])
			except Exception as e:
				response.status = falcon.get_http_status(498)
				print(e)

				error = {
					"token": False,
					"error": str(e),
				}
				return error
		
		elif method == "token":
			for rk in ('url', 'username', 'password', 'uuid'):
				if not rk in body:
					response.status = falcon.get_http_status(400)
					return {
						"token": False,
						"error": f'Missing {rk}'
					}

			try:
				client = pronotepy.Client.token_login(
					pronote_url = body['url'],
					username = body['username'],
					password = body['password'],
					uuid=body['uuid']
				)
			except Exception as e:
				response.status = falcon.get_http_status(498)
				print(f"Error while trying to connect to {body['url']}")
				print(e)

				error = {
					"token": False,
					"error": str(e),
				}
				return error

		token = secrets.token_urlsafe(16)

		# Set current period
		client.calculated_period = __get_current_period(client)
		print(client.calculated_period)
		client.activated_period = __get_current_period(client, False, None, True)

		saved_clients[token] = {
			'client': client,
			'last_interaction': time.time()
		}

		print(len(saved_clients), 'valid tokens')

		# if error return error
		if client.logged_in:
			if method != "url":
				QRtokenArray = {
					"token": token,
					"error": False,
					"qr_credentials": {
						"username": client.username,
						"password": client.password,
						"url": client.pronote_url
					}
				}

				return QRtokenArray

			tokenArray = {
				"token": token,
				"error": False
			}
			return tokenArray
		else:
			response.status = falcon.get_http_status(498)
			error = {
				"token": False,
				"error": "Login failed",
			}
			return error
	else:
		response.status = falcon.get_http_status(400)
		error = {
			"token": False,
			"error": "missingbody",
		}
		return error


# TODO: METTRE A JOUR CETTE PARTIE SI DES PROBLEMES APPARAISSENT
# Peut poser problème avec certains établissements
def __get_current_period(client: pronotepy.Client, wantSpecificPeriod: bool = False, specificPeriod: str = None, wantAllPeriods: bool = False) -> pronotepy.Period:
	"""
	Permet de récupérer la période actuelle du client Pronote ou une période spécifique.
	
	Args:
		client (pronotepy.Client): Le client Pronote
		wantSpecificPeriod (bool, optional): Si True, la fonction va retourner la période spécifiée par specificPeriod. Si False, la fonction va retourner la période actuelle. Defaults to False.
		specificPeriod (str, optional): La période à retourner. Defaults to None.
		wantAllPeriods (bool, optional): Si True, la fonction va retourner toutes les périodes. Defaults to False.
		
	Returns:
		pronotepy.Period: La période actuelle ou la période spécifiée.
	"""
	
	if client.logged_in:
		if not wantSpecificPeriod:
			CURRENT_PERIOD_NAME = client.current_period.name.split(' ')[0]
			if CURRENT_PERIOD_NAME == 'Trimestre':
				CURRENT_PERIOD_NAME = 'Trimestre'
			elif CURRENT_PERIOD_NAME == 'Semestre':
				CURRENT_PERIOD_NAME = 'Semestre'
			elif CURRENT_PERIOD_NAME == 'Année':
				CURRENT_PERIOD_NAME = 'Année'
			else:
				print("WARN: Couldn't find current period name")
				return client.current_period
			
			allPeriods = []
			currentPeriods = []

			for period in client.periods:
				if period.name.split(' ')[0] == CURRENT_PERIOD_NAME:
					currentPeriods.append(period)

			for i in range(len(currentPeriods)):
				period = currentPeriods[i]
				if not wantAllPeriods:   
					raw = datetime.datetime.now().date()
					now = datetime.datetime(raw.year, raw.month, raw.day)

					if period.start <= now <= period.end:
						return period

					if i == len(currentPeriods) - 1:
						return period
				else:
					allPeriods.append(period)
			
			return allPeriods
		else:
			for period in client.periods:
				if period.name == specificPeriod:
					return period
			print("WARN: Couldn't find specific period name")
			return __get_current_period(client, False, None)


@hug.post('/changePeriod')
def change_period(token: str, response, periodName: str):
	"""
	Permets de changer la période actuelle du client Pronote.
	
	Args:
		token (str): Le token du client Pronote
		response (falcon.Response): La réponse de la requête
		periodName (str): Le nom de la période à sélectionner
		
	Returns:
		dict[str, str]: Le statut de la requête et le nom de la période sélectionnée
	"""
	
	success, client = get_client(token)
	if success == 'ok':
		if client.logged_in:
			try:
				client.calculated_period = __get_current_period(client, True, periodName)
				return {
					'status': 'ok',
					'period': client.calculated_period.name
				}
			except Exception as e:
				response.status = falcon.get_http_status(500)
				return {
					'status': 'error',
					'message': str(e)
				}
	else:
		response.status = falcon.get_http_status(498)
		return success


@hug.get('/user')
def user(token: str, response):
	"""
	Récupère les informations de l'utilisateur.
	
	Args:
		token (str): Le token du client Pronote
		response (falcon.Response): La réponse de la requête
		
	Returns:
		dict: Les informations de l'utilisateur sous la forme : 
		
		{ 
			"name": str,
			"class": str, 
			"establishment": str, 
			"phone": str,
			"address": list[str], 
			"email": str,
			"ine": str,
			"profile_picture": str|None, 
			"delegue": bool, 
			"periodes": list[dict] 
		}
	"""
	
	success, client = get_client(token)
	if success == 'ok':
		if client.logged_in:
			periods = []
			for period in client.periods:
				periods.append({
					'start': period.start.strftime('%Y-%m-%d'),
					'end': period.end.strftime('%Y-%m-%d'),
					'name': period.name,
					'id': period.id,
					'actual': client.calculated_period.id == period.id
				})

			etabData = ""
			try:
				etabData = client.info.establishment
			except Exception as err:
				etabData = ""

			phone = ""
			try:
				phone = client.info.phone
			except Exception as err:
				phone = ""

			email = ""
			try:
				email = client.info.email
			except Exception as err:
				email = ""

			address = []
			try:
				address = client.info.address
			except Exception as err:
				address = []

			ine_number = ""
			try:
				ine_number = client.info.ine_number
			except Exception as err:
				ine_number = ""

			usertype = type(client).__name__

			children = []
			if (usertype == "ParentClient"):
				try:
					children = client.children.to_dict()
				except Exception as err:
					children = []

			userData = {
				"name": client.info.name,
				"class": client.info.class_name,
				"establishment": etabData,
				"phone": phone,
				"email": email,
				"address": address,
				"ine": ine_number,
				"profile_picture": client.info.profile_picture.url if client.info.profile_picture else None,
				"delegue": client.info.delegue,
				"periods": periods,
				"client": {
					"type": usertype,
					"children": children
				}
			}

			return userData
	else:
		response.status = falcon.get_http_status(498)
		return success


@hug.get('/timetable')
def timetable(token: str, dateString: str, response):
	"""
	Récupère l'emploi du temps de l'utilisateur.
	
	Args:
		token (str): Le token du client Pronote
		dateString (str): La date à récupérer sous la forme YYYY-MM-DD
		response (falcon.Response): La réponse de la requête
		
	Returns:
		list[dict]: Les informations de l'emploi du temps :
		
		[{
			"id": str,
			"num": int,
			"subject": {
				"id": str,
				"name": str,
				"groups": bool
			},
			"teachers": list[str],
			"rooms": list[str],
			"group_names": list[str]
			"start": str,
			"end": str,
			"duration": int
			"is_cancelled": bool,
			"is_outing": bool,
			"is_detention": bool,
			"is_exempted": bool,
			"is_test": bool,
		}]
	"""
	
	dateToGet = datetime.datetime.strptime(dateString, "%Y-%m-%d").date()
	success, client = get_client(token)

	if success == 'ok':
		if client.logged_in:
			lessons = client.lessons(dateToGet)

			lessonsData = []
			for lesson in lessons:
				files = []
				lessonContent = []

				if lesson.content != None:
					for file in lesson.content.files:
						files.append({
							"id": file.id,
							"name": file.name,
							"url": file.url,
							"type": file.type
						})

					lessonContent = {
						"title": lesson.content.title,
						"description": lesson.content.description,
						"category": lesson.content.category,
						"files": files
					}

				lessonData = {
					"id": lesson.id,
					"num": lesson.num,
					"subject": {
						"id": lesson.subject.id if lesson.subject is not None else "0",
						"name": lesson.subject.name if lesson.subject is not None else "",
						"groups": lesson.subject.groups if lesson.subject is not None else False
					},
					"teachers": lesson.teacher_names,
					"rooms": lesson.classrooms,
					"group_names": lesson.group_names,
					"memo": lesson.memo,
					"content": lessonContent,
					"virtual": lesson.virtual_classrooms,
					"start": lesson.start.strftime("%Y-%m-%d %H:%M"),
					"end": lesson.end.strftime("%Y-%m-%d %H:%M"),
					"background_color": lesson.background_color,
					"status": lesson.status,
					"is_cancelled": lesson.canceled,
					"is_outing": lesson.outing,
					"is_detention": lesson.detention,
					"is_exempted": lesson.exempted,
					"is_test": lesson.test,
				}
				lessonsData.append(lessonData)

			return lessonsData
	else:
		response.status = falcon.get_http_status(498)
		return success

@hug.get('/content')
def content(token: str, dateString: str, response):
	"""
	Récupère le contenu des cours.
	
	Args:
		token (str): Le token du client Pronote
		dateString (str): La date à récupérer sous la forme YYYY-MM-DD
		response (falcon.Response): La réponse de la requête
		
	Returns:
		list[dict]: Les contenus du cours 
	"""
	
	dateToGet = datetime.datetime.strptime(dateString, "%Y-%m-%d").date()
	success, client = get_client(token)

	if success == 'ok':
		if client.logged_in:
			content = client.lessons(dateToGet, dateToGet)

			contentData = []
			for lesson in content:
				if lesson.content != None:
					for contentElement in lesson.content:
						files = []
						for file in contentElement.files:
							files.append({
								"id": file.id,
								"name": file.name,
								"url": file.url,
								"type": file.type
							})
						
						contentList = {
							"title": contentElement.title,
							"description": contentElement.description,
							"category": contentElement.category,
							"files": files
						}

				contentData.append(contentList)

			return contentData
	else:
		response.status = falcon.get_http_status(498)
		return success

@hug.get('/homework')
def homework(token: str, dateFrom: str, dateTo: str, response):
	"""
	Récupère les devoirs de l'utilisateur.
	
	Args:
		token (str): Le token du client Pronote
		dateFrom (str): La date de début à récupérer sous la forme YYYY-MM-DD
		dateTo (str): La date de fin à récupérer sous la forme YYYY-MM-DD
		response (falcon.Response): La réponse de la requête
		
	Returns:
		list[dict]: Les informations des devoirs :

		{
			"id": str,
			"subject": {
				"id": str,
				"name": str,
				"groups": bool
			},
			"description": str,
			"background_color": str,
			"date": str,
			"files": list[dict {
				"id": str,
				"name": str,
				"url": str,
				"type": int
			}]
		}
	"""
	
	dateFrom = datetime.datetime.strptime(dateFrom, "%Y-%m-%d").date()
	dateTo = datetime.datetime.strptime(dateTo, "%Y-%m-%d").date()
	success, client = get_client(token)

	if success == 'ok':
		if client.logged_in:
			homeworks = client.homework(date_from=dateFrom, date_to=dateTo)

			homeworksData = []
			for homework in homeworks:
				files = []
				for file in homework.files:
					files.append({
						"id": file.id,
						"name": file.name,
						"url": file.url,
						"type": file.type
					})

				local_id = ""

				# return a combination of the 20 first letters of description, 2 first letters of subject name and the date
				if len(homework.description) > 20:
					local_id += homework.description[:20]
				else:
					local_id += homework.description
				
				local_id += homework.subject.name[:2]
				local_id += homework.date.strftime("%Y-%m-%d_%H:%M")

				homeworkData = {
					"id": homework.id,
					"local_id": local_id,
					"subject": {
						"id": homework.subject.id,
						"name": homework.subject.name,
						"groups": homework.subject.groups,
					},
					"description": homework.description,
					"background_color": homework.background_color,
					"done": homework.done,
					"date": homework.date.strftime("%Y-%m-%d %H:%M"),
					"files": files
				}
				homeworksData.append(homeworkData)

			return homeworksData
	else:
		response.status = falcon.get_http_status(498)
		return success


def __get_grade_state(grade_value:str, significant:bool = False) -> int|str :
	"""
	Récupère l'état d'une note sous forme d'int. (Non Rendu, Absent, etc.)
	
	Args:
		grade_value (str): La valeur de la note
		significant (bool): Si on souhaite récupérer l'état de la note ou la note elle-même. Si True on récupère l'état sous la forme d'un int :
			1 : Absent
			2 : Dispensé
			3 : Non Noté
			4 : Inapte
			5 : Non Rendu
			6 : Absent compte 0
			7 : Non Rendu compte 0
			8 : Félicitations
			Si False on récupère la note elle-même ou -1 si la note ne compte pas comme telle. Defaults to False.
		
	Returns:
		int|str: L'état de la note sous forme d'int ou la note elle-même (str) si significant est False.    
	"""
	
	grade_value = str(grade_value)

	if significant:
		grade_translate = [
			"Absent",
			"Dispense",
			"NonNote",
			"Inapte",
			"NonRendu",
			"AbsentZero",
			"NonRenduZero",
			"Felicitations"
		]
		try:
			int(grade_value[0])
			return 0
		except (ValueError, IndexError):
			if grade_value == "":
				return -1
			return grade_translate.index(grade_value) + 1
	else:
		try:
			int(grade_value[0])
			return grade_value
		except (ValueError, IndexError):
			return "-1"


def __transform_to_number(value:str)->float|int:
	"""
	Transforme une valeur en nombre (int ou float)
	
	Args:
		value (str): La valeur à transformer
		
	Returns:
		float|int: La valeur transformée ('1,5' -> 1.5)
	"""
	
	try:
		return int(value)
	except ValueError:
		return float(value.replace(",", "."))


@hug.get('/grades')
def grades(token: str, response):
	"""
	Récupère les notes de l'utilisateur.
	
	Args:
		token (str): Le token du client Pronote
		response (falcon.Response): La réponse de la requête
		
	Returns:
		dict: Les informations des notes :
		
		{
			grades : [{
				"id": str,
				"subject": {
					"id": str,
					"name": str,
					"groups": bool
				},
				"date": str,
				"description": str,
				"is_bonus": bool,
				"is_optional": bool,
				"is_out_of_20": bool,
				"grade": {
					"value": int,
					"out_of": int,
					"coefficient": int,
					"average": int,
					"max": int,
					"min": int,
					"significant": int
				},
			}],
			"average": [{
				"subject": {
					"id": str,
					"name": str,
					"groups": bool
				},
				"average": int,
				"class_average": int,
				"max": int,
				"min": int,
				"out_of": int,
				"significant": int
			}],
			"overall_average": int,
			"class_overall_average": int,
		}
	"""
	
	success, client = get_client(token)
	if success == 'ok':
		allGrades = client.calculated_period.grades
		gradesData = []
		for grade in allGrades:
			gradeData = {
				"id": grade.id,
				"subject": {
					"id": grade.subject.id,
					"name": grade.subject.name,
					"groups": grade.subject.groups,
				},
				"date": grade.date.strftime("%Y-%m-%d %H:%M"),
				"description": grade.comment,
				"is_bonus": grade.is_bonus,
				"is_optional": grade.is_optionnal,
				"is_out_of_20": grade.is_out_of_20,
				"grade": {
					"value": __transform_to_number(__get_grade_state(grade.grade)),
					"out_of": __transform_to_number(grade.out_of),
					"coefficient": __transform_to_number(grade.coefficient),
					"average": __transform_to_number(__get_grade_state(grade.average)),
					"max": __transform_to_number(__get_grade_state(grade.max)),
					"min": __transform_to_number(__get_grade_state(grade.min)),
					"significant": __get_grade_state(grade.grade, True),
				}
			}

			gradesData.append(gradeData)

		averagesData = []

		allAverages = client.calculated_period.averages
		for average in allAverages:
			averageData = {
				"subject": {
					"id": average.subject.id,
					"name": average.subject.name,
					"groups": average.subject.groups,
				},
				"average": __transform_to_number(__get_grade_state(average.student)),
				"class_average": __transform_to_number(__get_grade_state(average.class_average)),
				"max": __transform_to_number(__get_grade_state(average.max)),
				"min": __transform_to_number(__get_grade_state(average.min)),
				"out_of": __transform_to_number(__get_grade_state(average.out_of)),
				"significant": __get_grade_state(average.student, True),
				"color": average.background_color if average.background_color != None else "#08BE88"
			}

			averagesData.append(averageData)

		gradeReturn = {
			"grades": gradesData,
			"averages": averagesData,
			"overall_average": __transform_to_number(__get_grade_state(client.calculated_period.overall_average)),
			"class_overall_average": __transform_to_number(__get_grade_state(client.calculated_period.class_overall_average)),
		}

		return gradeReturn
	else:
		response.status = falcon.get_http_status(498)
		return success


@hug.get('/absences')
def absences(token: str, response, allPeriods: bool = True):
	"""
	Récupère les absences de l'utilisateur.
	
	Args:
		token (str): Le token du client Pronote
		response (falcon.Response): La réponse de la requête
		allPeriods (bool): Si toutes les périodes doivent être récupérées. Par défaut, toutes les périodes sont récupérées.
		
	Returns:
		list[dict]: Les informations des absences :
		
		[{
			"id": str,
			"from": str,
			"to": str,
			"justified": bool,
			"hours": int,
			"reasons": list[str],
		}]
	"""
	
	success, client = get_client(token)
	if success == 'ok':
		if allPeriods:
			allAbsences = [absence for period in client.activated_period for absence in period.absences]
		else:
			allAbsences = client.calculated_period.absences

		absencesData = []
		for absence in allAbsences:
			absenceData = {
				"id": absence.id,
				"from": absence.from_date.strftime("%Y-%m-%d %H:%M"),
				"to": absence.to_date.strftime("%Y-%m-%d %H:%M"),
				"justified": absence.justified,
				"hours": absence.hours,
				"reasons": absence.reasons,
			}

			absencesData.append(absenceData)

		return absencesData
	else:
		response.status = falcon.get_http_status(498)
		return success


@hug.get('/delays')
def delays(token: str, response, allPeriods: bool = True):
	"""
	Récupère les retards de l'utilisateur.
	
	Args:
		token (str): Le token du client Pronote
		response (falcon.Response): La réponse de la requête
		allPeriods (bool): Si toutes les périodes doivent être récupérées. Par défaut, toutes les périodes sont récupérées.
		
	Returns:
		list[dict]: Les informations des retards :
		
		[{
			"id": str,
			"date": str,
			"duration": int,
			"justified": bool,
			"justification": str,
			"reasons": list[str]
		}]
	"""
	
	success, client = get_client(token)
	if success == 'ok':
		if allPeriods:
			allDelays = [delay for period in client.activated_period for delay in period.delays]
		else:
			allDelays = client.calculated_period.delays
		
		delaysData = []
		for delay in allDelays:
			delayData = {
				"id": delay.id,
				"date": delay.date.strftime("%Y-%m-%d %H:%M"),
				"duration": delay.minutes,
				"justified": delay.justified,
				"justification": delay.justification,
				"reasons": delay.reasons,
			}

			delaysData.append(delayData)

		return delaysData
	else:
		response.status = falcon.get_http_status(498)
		return success


@hug.get('/punishments')
def punishments(token: str, response, allPeriods: bool = True):
	"""
	Récupère les punitions de l'utilisateur.
	
	Args:
		token (str): Le token du client Pronote
		response (falcon.Response): La réponse de la requête
		allPeriods (bool): Si toutes les périodes doivent être récupérées. Par défaut, toutes les périodes sont récupérées.
		
	Returns:
		list[dict]: Les informations des punitions :
		
		[{
			"id": str,
			"schedulable": bool,
			"schedule": [
				{
					"id": str,
					"start": str,
					"duration": int,
			],
			"date": str,
			"given_by": str,
			"exclusion:" bool,
			"during_lesson": bool,
			"homework": {
				"text": str,
				"documents": [{
					"id": str,
					"name": str,
					"url": str,
					"type": int,
				}],
			},
			"reasons": {
				"text": str,
				"circumstances": str,
				"documents": [{
					"id": str,
					"name": str,
					"url": str,
					"type": int,
				}],
			},
			"nature": str,
			"duration": int,
		}]
	"""
	
	success, client = get_client(token)
	if success == 'ok':
		if allPeriods:
			allPunishments = [punishment for period in client.activated_period for punishment in period.punishments]
		else:
			allPunishments = client.calculated_period.punishments
		
		punishmentsData = []
		for punishment in allPunishments:
			homeworkDocs = []
			if punishment.homework_documents is not None:
				for homeworkDoc in punishment.homework_documents:
					homeworkDocs.append({
						"id": homeworkDoc.id,
						"name": homeworkDoc.name,
						"url": homeworkDoc.url,
						"type": homeworkDoc.type
					})

			circumstanceDocs = []
			if punishment.circumstance_documents is not None:
				for circumstanceDoc in punishment.circumstance_documents:
					circumstanceDocs.append({
						"id": circumstanceDoc.id,
						"name": circumstanceDoc.name,
						"url": circumstanceDoc.url,
						"type": circumstanceDoc.type
					})

			schedules = []
			if punishment.schedule is not None:
				for schedule in punishment.schedule:
					schedules.append({
						"id": schedule.id,
						"start": schedule.start.strftime("%Y-%m-%d %H:%M"),
						"duration": schedule.duration,
					})

			punishmentData = {
				"id": punishment.id,
				"schedulable": punishment.schedulable,
				"schedule": schedules,
				"date": punishment.given.strftime("%Y-%m-%d %H:%M"),
				"given_by": punishment.giver,
				"exclusion": punishment.exclusion,
				"during_lesson": punishment.during_lesson,
				"homework": {
					"text": punishment.homework,
					"documents": homeworkDocs,
				},
				"reason": {
					"text": punishment.reasons,
					"circumstances": punishment.circumstances,
					"documents": circumstanceDocs,
				},
				"nature": punishment.nature,
				"duration": punishment.duration
			}

			punishmentsData.append(punishmentData)

		return punishmentsData
	else:
		response.status = falcon.get_http_status(498)
		return success


@hug.get('/news')
def news(token: str, response):
	"""
	Récupère les actualités de l'utilisateur.
	
	Args:
		token (str): Le token du client Pronote
		response (falcon.Response): La réponse de la requête
		
	Returns:
		list[dict]: Les informations des actualités :
		
		[{
			"id": str,
			"title": str,
			"date": str,
			"category": str,
			"read": bool,
			"survey": bool,
			"anonymous_survey": bool,
			"author": str,
			"content": str,
			"attachments": [{
				"id": str,
				"name": str,
				"url": str,
				"type": int,
			}],
			"html_content": str,
		}]
	"""
 
	success, client = get_client(token)
	if success == 'ok':
		allNews = client.information_and_surveys()

		newsAllData = []
		for news in allNews:
			local_id = ""

			# return a combination of the 20 first letters of content, 2 first letters of title and the date

			local_id += news.title[:3]

			local_id += news.creation_date.strftime("%Y-%m-%d_%H:%M")

			attachments = []
			if news.attachments is not None:
				for attachment in news.attachments:
					attachments.append({
						"id": attachment.id,
						"name": attachment.name,
						"url": attachment.url,
						"type": attachment.type
					})

			newsData = {
				"id": news.id,
				"local_id": local_id,
				"title": news.title,
				"date": news.creation_date.strftime("%Y-%m-%d %H:%M"),
				"category": news.category,
				"read": news.read,
				"survey": news.survey,
				"anonymous_survey": news.anonymous_response,
				"author": news.author,
				"content": news.content,
				"attachments": attachments,
				"html_content": news._raw_content
			}

			newsAllData.append(newsData)

		return newsAllData
	else:
		response.status = falcon.get_http_status(498)
		return success

@hug.post('/news/markAsRead')
def read_news(token: str, newsId: str, response):
	"""
	Change l'état de lecture d'une actualité.

	Args:
		token (str): Le token du client Pronote
		newsId (str): L'identifiant de l'actualité
		response (falcon.Response): La réponse de la requête

	Returns:

	"""

	success, client = get_client(token)
	if success == 'ok':
		if client.logged_in:
			try:
				allNews = client.information_and_surveys()

				for news in allNews:
					local_id = ""

					# return a combination of the 20 first letters of content, 2 first letters of title and the date

					local_id += news.title[:3]
					local_id += news.creation_date.strftime("%Y-%m-%d_%H:%M")

					if local_id == newsId:
						current_state = news.read

						news.mark_as_read(not news.read)
						current_state = not news.read
							
						return {
							"status": "ok",
							"current_state": current_state,
							"error": None
						}
					
				response.status = falcon.get_http_status(404)
				return {
					"status": "not found",
					"error": "L'actualité n'a pas été trouvée."
				}
	
			except Exception as e:
				response.status = falcon.get_http_status(500)
				return {
					"status": "error",
					"error": str(e)
				}

@hug.get('/discussions')
def discussions(token: str, response):
	"""
	Récupère les discussions de l'utilisateur.
	
	Args:
		token (str): Le token du client Pronote
		response (falcon.Response): La réponse de la requête
		
	Returns:
		list[dict]: Les informations des discussions :
		
		[{
			"id": str,
			"subject": str,
			"creator": str,
			"participants": list[str],
			"date": str,
			"unread": int,
			"replyable": bool,
			"messages": [{
				"id": str,
				"content": str,
				"author": str,
				"date": str,
				"seen": bool,
			}],
		}]
	"""
	
	success, client = get_client(token)
	if success == 'ok':
		allDiscussions = client.discussions()

		discussionsAllData = []
		for discussion in allDiscussions:
			messages = []
			for message in discussion.messages:
				messages.append({
					"id": message.id,
					"content": message.content,
					"author": message.author,
					"date": message.date.strftime("%Y-%m-%d %H:%M") if message.date is not None else None,
					"seen": message.seen
				})

			local_id = ""

			try:
				# return a combination of the 20 first letters of subject, 2 first letters of creator and the date
				local_id += discussion.subject[:3]
				local_id += discussion.creator[:3]
				local_id += discussion.date.strftime("%Y-%m-%d_%H:%M")
			except Exception as e:
				local_id += discussion.date.strftime("%Y-%m-%d_%H:%M")

			participants = []
			try :
				participants = discussion.participants()
			except Exception as e:
				participants = []

			discussionData = {
				"local_id": local_id,
				"subject": discussion.subject,
				"creator": discussion.creator,
				"date": discussion.date.strftime("%Y-%m-%d %H:%M") if discussion.date is not None else None,
				"unread": discussion.unread,
				"closed": discussion.close,
				"replyable": discussion.replyable,
				"messages": messages,
				"participants": participants
			}

			discussionsAllData.append(discussionData)

		return discussionsAllData
	else:
		response.status = falcon.get_http_status(498)
		return success


@hug.post('/discussion/delete')
def delete_discussion(token: str, discussionId: str, response):
	"""
	Supprime une discussion.
	
	Args:
		token (str): Le token du client Pronote
		discussionId (str): L'identifiant de la discussion
		response (falcon.Response): La réponse de la requête
		
	Returns:
		str: 'ok' si la discussion a été supprimée, 'not found' si la discussion n'a pas été trouvée, 'error' si une erreur est survenue.
	"""
	
	success, client = get_client(token)
	if success == 'ok':
		try:
			allDiscussions = client.discussions()
			for discussion in allDiscussions:
				local_id = ""

				try:
					# return a combination of the 20 first letters of subject, 2 first letters of creator and the date
					local_id += discussion.subject[:3]
					local_id += discussion.creator[:3]
					local_id += discussion.date.strftime("%Y-%m-%d_%H:%M")
				except Exception as e:
					local_id += discussion.date.strftime("%Y-%m-%d_%H:%M")

				if local_id == discussionId:
					discussion.delete()
					return {
						"status": "ok",
						"error": None
					}
				else:
					response.status = falcon.get_http_status(404)
					return {
						"status": "not found",
						"error": "La discussion n'a pas été trouvée."
					}
		except Exception as e:
			response.status = falcon.get_http_status(500)
			return {
				"status": "error",
				"error": str(e)
			}
	else:
		response.status = falcon.get_http_status(498)
		return success

@hug.post('/discussion/readState')
def read_discussion(token: str, discussionId: str, response):
	"""
	Change l'état de lecture d'une discussion.
	
	Args:
		token (str): Le token du client Pronote
		discussionId (str): L'identifiant de la discussion
		response (falcon.Response): La réponse de la requête
		
	Returns:
		str: 'ok' si l'état de lecture a été changé, 'not found' si la discussion n'a pas été trouvée, 'error' si une erreur est survenue.
	"""
	
	success, client = get_client(token)
	if success == 'ok':
		try:
			allDiscussions = client.discussions()
			for discussion in allDiscussions:
				local_id = ""

				try:
					# return a combination of the 20 first letters of subject, 2 first letters of creator and the date
					local_id += discussion.subject[:3]
					local_id += discussion.creator[:3]
					local_id += discussion.date.strftime("%Y-%m-%d_%H:%M")
				except Exception as e:
					local_id += discussion.date.strftime("%Y-%m-%d_%H:%M")

				if local_id == discussionId:
					if discussion.unread == 0: discussion.mark_as(False)
					else: discussion.mark_as(True)
					return {
						"status": "ok",
						"error": None
					}
				else:
					response.status = falcon.get_http_status(404)
					return {
						"status": "not found",
						"error": "La discussion n'a pas été trouvée."
					}
		except Exception as e:
			response.status = falcon.get_http_status(500)
			return {
				"status": "error",
				"error": str(e)
			}
	else:
		response.status = falcon.get_http_status(498)
		return success

@hug.post('/discussion/reply')
def reply_discussion(token: str, discussionId: str, content: str, response):
	"""
	Répond à une discussion.
	
	Args:
		token (str): Le token du client Pronote
		discussionId (str): L'identifiant de la discussion
		content (str): Le contenu du message
		response (falcon.Response): La réponse de la requête
		
	Returns:
		str: 'ok' si le message a été envoyé, 'not replyable' si la discussion n'est pas ouverte à la réponse, 'not found' si la discussion n'a pas été trouvée, 'error' si une erreur est survenue.
	"""
	
	success, client = get_client(token)
	if success == 'ok':
		try:
			allDiscussions = client.discussions()
			for discussion in allDiscussions:
				local_id = ""

				try:
					# return a combination of the 20 first letters of subject, 2 first letters of creator and the date
					local_id += discussion.subject[:3]
					local_id += discussion.creator[:3]
					local_id += discussion.date.strftime("%Y-%m-%d_%H:%M")
				except Exception as e:
					local_id += discussion.date.strftime("%Y-%m-%d_%H:%M")

				if local_id == discussionId:
					if discussion.replyable:
						discussion.reply(content)
						return {
							"status": "ok",
							"error": None
						}
					else:
						response.status = falcon.get_http_status(403)
						return {
							"status": "not replyable",
							"error": "La discussion n'est pas ouverte à la réponse."
						}
				else:
					response.status = falcon.get_http_status(404)
					return {
						"status": "not found",
						"error": "La discussion n'a pas été trouvée."
					}
		except Exception as e:
			response.status = falcon.get_http_status(500)
			return {
				"status": "error",
				"error": str(e)
			}
	else:
		response.status = falcon.get_http_status(498)
		return success


@hug.get('/recipients')
def recipients(token: str, response):
	"""
	Récupère la liste des destinataires possibles.
	
	Args:
		token (str): Le token du client Pronote
		response (falcon.Response): La réponse de la requête
		
	Returns:
		list: La liste des destinataires possibles.
		
		[{
			"id": str,
			"name": str,
			"type": str,
			"email": str,
			"functions": list[str],
			"with_discussion": bool
		}]
	"""
	
	success, client = get_client(token)
	if success == 'ok':
		allRecipients = client.get_recipients()

		recipientsAllData = []
		for recipient in allRecipients:
			recipientData = {
				"id": recipient.id,
				"name": recipient.name,
				"type": recipient.type,
				"email": recipient.email,
				"functions": recipient.functions,
				"with_discussion": recipient.with_discussion
			}

			recipientsAllData.append(recipientData)
		
		return recipientsAllData
	else:
		response.status = falcon.get_http_status(498)
		return success


@hug.post('/discussion/create')
def create_discussion(token: str, subject: str, content: str, recipientsId: str, response):
	"""
	Créer une discussion.
	
	Args:
		token (str): Le token du client Pronote
		subject (str): Le sujet de la discussion
		content (str): Le contenu du message
		recipientsId (str): La liste des identifiants des destinataires ([id1, id2, id3])
		response (falcon.Response): La réponse de la requête
		
	Returns:
		str: 'ok' si la discussion a été créée, 'error' si une erreur est survenue.
	"""
	
	success, client = get_client(token)
	if success == 'ok':
		try:
			prn_recipients = []
			for recipient in json.loads(recipientsId):
				for prn_recipient in client.get_recipients():
					if prn_recipient.id == recipient:
						prn_recipients.append(prn_recipient)
						
			if len(prn_recipients) == 0:
				response.status = falcon.get_http_status(400)
				return {
					"status": "no recipient",
					"error": "Aucun destinataire valide n'a été trouvé."
				}
				
			for prn_recipient in prn_recipients:
				if prn_recipient.with_discussion == False:
					response.status = falcon.get_http_status(400)
					return {
						"status": "recipient not accept discussion",
						"error": "Un ou plusieurs destinataires n'acceptent pas les discussions."
					}
					
			client.new_discussion(subject, content, prn_recipients)
			return {
				"status": "ok",
				"error": None
			}
		except Exception as e:            
			response.status = falcon.get_http_status(500)
			return {
				"status": "error",
				"error": str(e)
			}
	else:
		response.status = falcon.get_http_status(498)
		return success


@hug.get('/evaluations')
def evaluations(token: str, response):
	"""
	Permet de récupérer les évaluations.
	
	Args:
		token (str): Le token du client Pronote
		response (falcon.Response): La réponse de la requête
		
	Returns:
		list[dict]: La liste des évaluations.
		
		[{
			"id": str,
			"subject": {
				"id": str,
				"name": str,
				"groups": bool
			},
			"name": str,
			"description": str,
			"teacher": str, 
			"date": str,
			"palier": str,
			"coefficient": str,
			"acquisitions": [{
				"id": str,
				"name": str,
				"coefficient": str,
				"abbreviation": str,
				"domain": str,
				"level": str
			}],
		}]
	"""
	
	success, client = get_client(token)
	if success == 'ok':
		allEvaluations = client.calculated_period.evaluations

		evaluationsAllData = []
		for evaluation in allEvaluations:
			acquisitions = []
			if evaluation.acquisitions is not None:
				for acquisition in evaluation.acquisitions:
					acquisitions.append({
						"id": acquisition.id,
						"name": acquisition.name,
						"coefficient": acquisition.coefficient,
						"abbreviation": acquisition.abbreviation,
						"domain": acquisition.domain,
						"level": acquisition.level
					})

			evaluationData = {
				"id": evaluation.id,
				"subject": {
					"id": evaluation.subject.id,
					"name": evaluation.subject.name,
					"groups": evaluation.subject.groups,
				},
				"name": evaluation.name,
				"description": evaluation.description,
				"teacher": evaluation.teacher,
				"date": evaluation.date.strftime("%Y-%m-%d %H:%M"),
				"paliers": evaluation.paliers,
				"coefficient": evaluation.coefficient,
				"acquisitions": acquisitions,
			}

			evaluationsAllData.append(evaluationData)

		return evaluationsAllData
	else:
		response.status = falcon.get_http_status(498)
		return success

def __get_meal_food(meal: list[dict]):
	"""
	Permet de récupérer les aliments d'un repas.
	
	Args:
		meal (list): La liste des aliments du repas
		
	Returns:
		list[dict]: La liste des aliments du repas.
	"""
	
	if meal is None:
		return None
	else:
		foods = []
		for food in meal:
			foods.append({
				"name": food.name,
				"labels": __get_food_labels(food.labels),
			})
		return foods

def __get_food_labels(labels: list[dict]):
	"""
	Permet de récupérer les labels d'un aliment.
	
	Args:
		labels (list): La liste des labels de l'aliment
		
	Returns:
		list[dict]: La liste des labels de l'aliment.
	"""
	
	if labels is None:
		return None
	else:
		foodLabels = []
		for label in labels:
			foodLabels.append({
				"id": label.id,
				"name": label.name,
				"color": label.color,
			})
		return foodLabels

@hug.get('/menu')
def menu(token: str, dateFrom: str, dateTo: str, response):
	"""
	Permet de récupérer les menus.
	
	Args:
		token (str): Le token du client Pronote
		dateFrom (str): La date de début
		dateTo (str): La date de fin
		response (falcon.Response): La réponse de la requête
		
	Returns:
		list[dict]: La liste des menus.
		
		[{
			"id": str,
			"name": str,
			"date": str,
			"type": {
				"is_lunch": bool,
				"is_dinner": bool,
			},
			"first_meal": list[dict],
			"dessert": list[dict],
			"cheese": list[dict],
			"other_meal": list[dict],
			"side_meal": list[dict],
			"main_meal": list[dict],
		}]
	"""
	
	dateFrom = datetime.datetime.strptime(dateFrom, "%Y-%m-%d").date()
	dateTo = datetime.datetime.strptime(dateTo, "%Y-%m-%d").date()
	success, client = get_client(token)
	if success == 'ok':
		allMenus = client.menus(date_from=dateFrom, date_to=dateTo)

		menusAllData = []
		for menu in allMenus:
			cheese = __get_meal_food(menu.cheese)
			dessert = __get_meal_food(menu.dessert)
			other_meal = __get_meal_food(menu.other_meal)
			side_meal = __get_meal_food(menu.side_meal)
			main_meal = __get_meal_food(menu.main_meal)
			first_meal = __get_meal_food(menu.first_meal)

			menuData = {
				"id": menu.id,
				"name": menu.name,
				"date": menu.date.strftime("%Y-%m-%d"),
				"type": {
					"is_lunch": menu.is_lunch,
					"is_dinner": menu.is_dinner,
				},
				"first_meal": first_meal,
				"dessert": dessert,
				"cheese": cheese,
				"other_meal": other_meal,
				"side_meal": side_meal,
				"main_meal": main_meal,
			}

			menusAllData.append(menuData)

		return menusAllData
	else:
		response.status = falcon.get_http_status(498)
		return success

@hug.get('/export/ical')
def export_ical(token: str, response):
	"""
	Permet d'exporter les données de Pronote en iCal. (si l'instance de Pronote le permet)
	
	Args:
		token (str): Le token du client Pronote
		response (falcon.Response): La réponse de la requête
		
	Returns:
		str: L'URL de l'iCal.
	"""
	
	success, client = get_client(token)
	if success == 'ok':
		ical_url = client.export_ical()
		return ical_url
	else:
		response.status = falcon.get_http_status(498)
		return success


@hug.post('/homework/changeState')
def set_homework_as_done(token: str, dateFrom: str, dateTo: str, homeworkId: str, response):
	"""
	Change l'état d'un devoir. (fait ou non fait)
	
	Args:
		token (str): Le token du client Pronote
		dateFrom (str): La date de début
		dateTo (str): La date de fin
		homeworkId (str): Le LocaID du devoir
		response (falcon.Response): La réponse de la requête
		
	Returns:
		str: 'ok' si tout s'est bien passé, 'not found' si le devoir n'a pas été trouvé, 'error' si une erreur est survenue.
	"""
	
	dateFrom = datetime.datetime.strptime(dateFrom, "%Y-%m-%d").date()
	dateTo = datetime.datetime.strptime(dateTo, "%Y-%m-%d").date()
	success, client = get_client(token)

	if success == 'ok':
		if client.logged_in:
			try:
				homeworks = client.homework(date_from=dateFrom, date_to=dateTo)
				changed = False

				for homework in homeworks:
					local_id = ""

					# return a combination of the 20 first letters of description, 2 first letters of subject name and the date
					if len(homework.description) > 20:
						local_id += homework.description[:20]
					else:
						local_id += homework.description
					
					local_id += homework.subject.name[:2]
					local_id += homework.date.strftime("%Y-%m-%d_%H:%M")
					
					if local_id == homeworkId:
						current_state = homework.done
						if homework.done:
							homework.set_done(False)
							current_state = False
						else:
							homework.set_done(True)
							current_state = True
						changed = True
						return {
							"status": "ok",
							"current_state": current_state,
							"error": None
						}
				if not changed:
					response.status = falcon.get_http_status(404)
					return {
						"status": "not found",
						"error": "Aucun devoir trouvé avec cet ID local."
					}
			except Exception as e:
				response.status = falcon.get_http_status(500)
				return {
					"status": "error",
					"error": str(e)
				}
	else:
		response.status = falcon.get_http_status(498)
		return success
