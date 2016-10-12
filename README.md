# Samurai
Samurai is a demonstration of realtime communication between a python server and html5 clients.

The server creates a thread running a Python HTTPServer to send the interface to clients. It then opens a socket on an arbitrary port that listens for clients to connect through the web page. Once two players select "Play", the server creates a new thread that handles their game. Players' account data is stored and manipulated through Python's SQLite module.

Instructions:
* Run server.py either via command line or a Python IDE. Note: Opening port 80 usually requres root or admin privileges. Opening port 80 on Windows usually requires stopping the "Web Publishing" service.
* In a web browser (preferable mobile), connect to the server's ip.
* Enter login credentials and press Login to use an existing account, or Create to create a new account with the given credentials.
* Press Play. Once at least two connected clients have queued for a game, it will begin.
* The left side of the screen acts as a virtual joystick and the right side is the attack button.
* After the game, each player's elo score is updated and saved, and the players are allowed to queue for another.

Notes:
* The script for the virtual joystick was taken from https://github.com/jeromeetienne/virtualjoystick.js. All other code was written by me using default libraries.
* Tested on Chrome mobile and Safari mobile.
* The server identifies whether an incoming connection is from a Websocket and genreates the handshake accordingly.
* Communication between the client and server is sent in XML format. The client need not be a web browser, but could also be a mobile app that uses the same format for communication.
* The server is written in Python because I originally developed it on a Rasperry Pi that output the player's positions to an LED strip via SPI.
