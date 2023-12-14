echo "Papillon    ^=^z    EN COURS : Mise    jour repo api Papillon"
start_api() {
        # TAG_NAME = git describe --tags $(git rev-list --tags --max-count=1)
        rm -rf papillon-python
        pip install --upgrade pip
        pip uninstall pronotepy -y
        git rm --cached filename
        git clone -b development https://github.com/PapillonApp/papillon-python
        pip3.11 install -U https://github.com/bain3/pronotepy/archive/refs/heads/master.zip
        pip3.11 install -U lxml
        pip3.11 install -U hug
        pip3.11 install -U sentry-sdk
        cd papillon-python
        rm maintenance.json
        wget https://cdn.tryon-lab.fr/papillon/maintenance.json 
        echo "Papillon    ^|^e   Lancement de l'api"
        python3.11 -m hug -f server.py
}

while true; do
        start_api
        echo "If you want to completely stop the api process now, press Ctrl+C before the time is up!"
        for i in 5 4 3 2 1; do
                echo "Papillon    ^=^z    Red  marrage dans $i"
                sleep 1
        done
        echo "Papillon    ^=^z    Red  marrage de l'api"
done
