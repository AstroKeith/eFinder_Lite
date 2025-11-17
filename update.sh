#!/bin/sh
echo "eFinder Mini update"
echo " "
echo "*****************************************************************************"
echo "Updating Pi OS & other packages"
echo "*****************************************************************************"

venv-efinder/bin/python venv-efinder/bin/pip install grpcio
venv-efinder/bin/python venv-efinder/bin/pip install grpcio-tools

sudo -u efinder git clone https://github.com/smroid/cedar-detect.git
sudo -u efinder git clone https://github.com/smroid/cedar-solve.git

sudo wget https://github.com/astrokeith/efinder_lite/raw/main/Solver/cedar-detect-server
sudo cp cedar-detect-server Solver
sudo wget https://github.com/astrokeith/efinder_lite/raw/main/Solver/eFinder_mini.py
sudo cp eFinder_mini.py Solver

sudo rm -rf tetra*
sudo rm -rf venv-efinder/lib/python3.11/site-packages/tetra*
sudo wget https://github.com/astrokeith/efinder_lite/raw/main/tetra3.zip
unzip tetra3.zip
sudo cp -r tetra3 venv-efinder/lib/python3.11/site-packages
sudo venv-efinder/bin/gdown  --output /home/efinder/venv-efinder/lib/python3.11/site-packages/tetra3/data --folder https://drive.google.com/drive/folders/1uxbdttpg0Dpp8OuYUDY9arYoeglfZzcX
sudo chmod a+rwx -R /home/efinder/venv-efinder/lib/python3.11/site-packages/tetra3
