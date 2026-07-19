#!/bin/bash
# Prise vidéo pour la demande d'accès Standard Pinterest.
# L'enregistrement se fait avec l'outil natif macOS (⇧⌘5) piloté par Nicolas —
# le script affiche quoi faire et quand. Relançable à volonté (nouvelle prise).
MARKER="/private/tmp/claude-501/-Users-nicolasclement-Pro-Gardeco/6cd22e71-47bb-4278-a9db-76f007d4860d/scratchpad/take-done"
cd "$(dirname "$0")"
export PINTEREST_API_BASE=https://api-sandbox.pinterest.com
trap 'date > "$MARKER"' EXIT

clear
echo "Gardeco Social — Pinterest API demo"
echo
echo "Prépare l'écran : cette fenêtre à GAUCHE, le navigateur (onglet Pinterest"
echo "seul) à DROITE, tout le reste masqué. Démarre l'enregistrement (⇧⌘5),"
echo "puis reviens cliquer ici."
echo
read -r -p "Press Enter to start the demo..."
sleep 2
clear
echo "############################################################"
echo "#  Gardeco Social - Pinterest API v5 integration demo      #"
echo "#  Internal publishing tool for our own account @gardecoch #"
echo "#  Environment: API Sandbox (as required for Trial apps)   #"
echo "############################################################"
echo
sleep 4

echo "STEP 1 - Full OAuth authorization flow"
echo "$ python3 pinterest_auth.py login"
python3 pinterest_auth.py login
echo
sleep 4

echo "STEP 2 - Verify authenticated account"
echo "$ python3 pinterest_auth.py whoami"
python3 pinterest_auth.py whoami
echo
sleep 4

echo "STEP 3 - API action: create a board + a pin"
echo "$ python3 pinterest_auth.py pin-test"
python3 pinterest_auth.py pin-test
echo
sleep 4

echo "STEP 4 - Result: the created pin on our profile (Sandbox entities"
echo "         are visible to the authenticated owner)"
open "https://www.pinterest.com/gardecoch/"
echo
echo ">>> Clique sur le tableau « Robots de piscine — sandbox » pour montrer le pin."
sleep 25
echo
echo "⏹  FIN — arrête l'enregistrement : bouton ⏺/⏹ dans la barre des menus"
echo "   (ou ⇧⌘5 → Arrêter). Le fichier .mov arrive sur le Bureau."
