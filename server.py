import socket
import hashlib, base64, string
import xml.etree.ElementTree as ET
import time
import threading
import random
import struct
import SimpleHTTPServer
import SocketServer
import sqlite3
import math

# Declare global variables
ws = None
clients = []
rooms = [1]
closeByte = bytearray(0xFF)

def to_bytes(n, length, endianess='big'):
    h = '%x' % n
    s = ('0'*(len(h) % 2) + h).zfill(length*2).decode('hex')
    return s if endianess == 'big' else s[::-1]

def frameMessage(s):
    """
    Encode and send a WebSocket message
    """

    message = ""
    # always send an entire message as one frame (fin)
    b1 = 0x80

    b1 |= 0x02
    payload = s

    message += chr(b1)

    # never mask frames from the server to the client
    b2 = 0
    length = len(payload)
    if length < 126:
        b2 |= length
        message += chr(b2)
    elif length < (2 ** 16) - 1:
        b2 |= 126
        message += chr(b2)
        l = struct.pack(">H", length)
        message += l
    else:
        l = struct.pack(">Q", length)
        b2 |= 127
        message += chr(b2)
        message += l

    message += payload

    return message

def socketListener():
    global clients
    clientLocal = threading.local()

    PORT = 35125 # Arbitrary port
    # Attempt to setup the socket every two seconds
    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(('', PORT))
            print 'Game server started.'
            break
        except:
            print 'Failed to setup server...'
            time.sleep(2)
    while(1):
        print 'Listening for connection...'
        s.listen(1) # Accept input from the socket
        conn, addr = s.accept()
        print 'Connection accepted from: ', addr , '.'

        # Create a new client by passing the socket and thread
        client = Client()
        client.conn = conn
        clients.append(client)

        # Start client thread
        ct = threading.Thread(target = clientThread, args = [s, conn, client])
        ct.daemon = True
        ct.start()

def normalize_line_endings(s):
    r'''Convert string containing various line endings like \n, \r or \r\n,
    to uniform \n.'''

    return ''.join((line + '\n') for line in s.splitlines())

# Thread that connects to and accepts messages from client
def clientThread(s, conn, client):
    global clients

    socketType = 0 # Type of socket: 0 is raw, 1 is websocket

    # Main Client Handler Loop
    while True:
        # If handshake hasn't occured yet, process input until it is made
        if client.connected is False:
            data = conn.recv(1024)
            if not data: continue
            #print data
            if data.find('clientJoin') is not -1:
                # Get websocket key, then generate and send response
                dataLines = data.splitlines()
                for line in dataLines:
                    if line.find('Sec-WebSocket-Key') is not -1:
                        key = line
                key = key.strip('Sec-WebSocket-Key: ')
                key = key[0:24]
                key = key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
                key = hashlib.sha1(key)
                key = key.digest()
                key = base64.b64encode(key)
                response = 'HTTP/1.1 101 Switching Protocols\r\n'
                response += 'Upgrade: websocket\r\n'
                response += 'Connection: Upgrade\r\n'
                response += 'Sec-WebSocket-Protocol: clientJoin\r\n'
                response += 'Sec-WebSocket-Accept: ' + key + '\r\n\r\n'
                conn.send(response)
                print 'Response sent.'
                client.connected = True
                socketType = 1
                client.state = 'connected'
                continue
            conn.send(closeByte)
            conn.shutdown(socket.SHUT_RDWR)
            conn.close()
            clients.remove(client)
            break
        # If handshake has occured, parse input and set variables for main game loop to use
        else:
            #Fetch data from buffer
            try:
                data = conn.recv(1024)
            except:
                continue
            if not data: continue # Continue if no data was received

            # If we are using a websocket, incoming data must be decoded from binary
            if socketType is 1:
                data = string.join(decodeCharArray(data), '')
                data = ''.join(filter(lambda x: x in string.printable, data))

            #print data
            #print '\n'

            # Extract the first <message> from the buffer
            messageStart = data.find('<message>')
            if messageStart is -1: continue # Continue if no valid <message> received
            data = data[messageStart:(len(data) - messageStart)]
            messageEnd = data.find('</message>') + 10
            data = data[0:messageEnd]
            client.lastInput = time.time() # Record time the message was received
            # Parse and process the <message>
            root = ET.fromstring(data)
            for child in root:
                if child.tag == 'disconnect':
                    client.state = 'disconnected'
                    client.conn.send(closeByte)
                    client.conn.shutdown(socket.SHUT_RDWR)
                    client.conn.close()
                    clients.remove(client)
                    break
            client.messages.append(root)





# Decodes a binary message into a readable string
def decodeCharArray(stringStreamIn):
        # Turn string values into opererable numeric byte values
        byteArray = [ord(character) for character in stringStreamIn]
        datalength = byteArray[1] & 127
        indexFirstMask = 2
        if datalength == 126:
            indexFirstMask = 4
        elif datalength == 127:
            indexFirstMask = 10
        # Extract masks
        masks = [m for m in byteArray[indexFirstMask : indexFirstMask+4]]
        indexFirstDataByte = indexFirstMask + 4
        # List of decoded characters
        decodedChars = []
        i = indexFirstDataByte
        j = 0
        # Loop through each byte that was received
        while i < len(byteArray):
            # Unmask this byte and add to the decoded buffer
            decodedChars.append( chr(byteArray[i] ^ masks[j % 4]) )
            i += 1
            j += 1
        # Return the decoded string
        return decodedChars

class Client(object):
    def __init__(self):
        self.conn = None
        self.uname = ''
        self.state = ''
        self.sessionId = 0
        self.actorId = 0
        self.axis_x = 0
        self.button_attack = 0
        self.lastInput = time.time()
        self.connected = False
        self.messages = []
        self.actor = None
        self.score = 0

# Class that defines properties of actors (players and enemies)
class Actor(object):
    def __init__(self):
        self.input_x = 0.0 # Movement input supplied by a client (players) or the AI method (enemies)
        self.input_attack = 0 # Attack input supplied by a client (players) or the AI method (enemies)
        self.maxHealth = 3
        self.health = 3
        self.speed = 2 # Base movement speed
        self.attackLength = 0.04 # How long an attack lasts
        self.attackSpeed = 4.0 # Movement speed during an attack
        self.attackTimer = 0.0 # Counts down while attacking. Attack ends at 0
        self.attackCooldown = 0. # Counts down after attacking. Can attack at 0
        self.attackRate = 1. # Seconds between attacks
        self.attackDirection = 1.0 # The direction this entity will attack in
        self.origin = 0 # This entity's starting position
        self.trigger = ''
        self.buttonReleased = True # Has the player released the attack button
        self.position = 0.0 # Current position
        self.id = 0 # A unique ID for the actor
        self.isAI = False # Is the player to be controlled by AI
        self.AItarget = None # AI ONLY- Player the AI will attack
        self.AITargetPos = 0.0 # AI ONLY- Position the AI wants to move to
        self.AIattackCooldown = 0.0 #AI ONLY- Counts down from a random value. AI attacks at 0
        self.dead = False;

# Returns a float that bounces between minimum and maximum at the given speed
def oscillate(minimum, maximum, speed):
    length = maximum - minimum
    l = length * 2
    t = (time.time() * speed) % l
    if 0 <= t < length:
        return t + minimum
    else:
        return l - t + minimum

# Resets actors' position and cooldown
def reset(actors):
    for entity in actors:
        entity.position = entity.origin
        entity.attackCooldown = 0
        entity.dead = False

# AI for actors. ActingEntity's input is set against the AITargetPosEntity
def AIthink(actor):
    target = actor.AItarget
    if actor.attackTimer > 0: return
    actor.input_x = 0 # Reset input
    distance = oscillate(5., 40., 20.) # Determine the distance to keep from the target
    # Determine which side of the target we are on, then set AITargetPos
    if target.position < actor.position:
        actor.AITargetPos = target.position + distance
    else:
        actor.AITargetPos = target.position - distance
    # Convert the AITargetPos to an integer
    actor.AITargetPos = int(actor.AITargetPos)
    # Determine whether the AI should attack
    if actor.AIattackCooldown < 0:
        actor.AIattackCooldown = random.random() * 12. + 1.5
        actor.input_attack = 1
        actor.AITargetPos = target.position
    # Set the entity's input to move towards the target
    if abs(actor.position - actor.AITargetPos) > 1:
        if (actor.position < actor.AITargetPos):
            actor.attackDirection = 1.0
            actor.input_x = 1.0
        else:
            actor.attackDirection = -1.0
            actor.input_x = -1.0

def run():
    db = sqlite3.connect('samurai.db')
    c = db.cursor()



    # Declare variables shared with server as Global
    global clients
    global rooms
    queued = []


    #Start HTTP server
    Handler = SimpleHTTPServer.SimpleHTTPRequestHandler
    httpd = SocketServer.TCPServer(("", 80), Handler)
    httpServerThread = threading.Thread(target = httpd.serve_forever)
    httpServerThread.daemon = True
    httpServerThread.start()
    print('HTTP server started.')

    # Start the socket listener
    listener = threading.Thread(target = socketListener)
    listener.daemon = True
    listener.start()

    while True:
        for client in clients:
            if client.state == 'connected':
                for message in client.messages:
                    for child in message:
                        if child.tag == 'request':
                            if child.attrib['type'] == 'login':
                                uname = child.attrib['uname']
                                pword = child.attrib['pword']
                                print 'Login Request Received:'
                                print 'Username: ' + uname
                                print 'Passord: ' + pword

                                loginSuccess = False
                                loginError = ''
                                c.execute('SELECT * FROM players where uname=?', (uname,))
                                result = c.fetchone()
                                if result is None:
                                    loginError = 'Username not found.'
                                else:
                                    if result[2] == pword:
                                        loginSuccess = True
                                    else:
                                        loginError = "Incorrect Password."
                                if loginSuccess is True:
                                    print 'Login Successful.'
                                    client.conn.send(frameMessage('<message><event type="loginSuccess" /></message>'))
                                    client.uname = uname
                                    client.state = 'loggedin'
                                else:
                                    client.conn.send(frameMessage('<message><event type="loginFail" reason="' + loginError + '" /></message>'))

                            if child.attrib['type'] == 'create':
                                uname = child.attrib['uname']
                                pword = child.attrib['pword']
                                createSuccess = False
                                createError = ''
                                c.execute('SELECT * FROM players where uname=?', (uname,))
                                result = c.fetchone()

                                if result is not None:
                                    createError = "Username already exists."
                                else:
                                    print 'creating player.'

                                    c.execute('''INSERT INTO players (id, uname, pword, elo) VALUES (?, ?, ?, ?)''', (1, uname, pword, 1000))
                                    db.commit()
                                    createSuccess = True
                                if createSuccess is True:
                                    print 'Creation Successful.'
                                    client.conn.send(
                                        frameMessage('<message><event type="loginSuccess" /></message>'))
                                    client.uname = uname
                                    client.state = 'loggedin'
                                else:
                                    client.conn.send(frameMessage(
                                        '<message><event type="loginFail" reason="' + createError + '" /></message>'))

                                #client.state = 'queued'
                                #queued.append(client)
                del client.messages[:]
            if client.state == 'loggedin':
                #print ('checking if connected client wants to queue up.')
                for message in client.messages:
                    for child in message:
                        if child.tag == 'request':
                            if child.attrib['type'] == 'play':
                                client.state = 'queued'
                                queued.append(client)
                del client.messages[:]

        if len(queued) > 1:
            print 'At least two players found. Creating room.'
            clist = [queued[0], queued[1]]
            newRoom = threading.Thread(target = room, args = [clist])
            newRoom.daemon = True
            newRoom.start()
            del queued[0]
            del queued[0]

        time.sleep(1)



def room(clist):
    clients = clist

    # Declare local variables
    frameLength = (1.0 / 30.0)  # Set the time to sleep between frames and amount to decrement from timers
    # Game States
    statePlay = 1
    statePause = 2
    stateGloat = 3
    stateEnd = 4
    gameState = stateGloat

    # Create player actors
    player1 = Actor()
    player1.id = 1


    player2 = Actor()
    player2.id = 2
    player2.origin = 100
    player2.position = 100

    clients[0].actor = player1
    clients[1].actor = player2

    db = sqlite3.connect('samurai.db')
    c = db.cursor()
    c.execute('SELECT elo FROM players where uname=?', (clients[0].uname,))
    clients[0].score = c.fetchone()[0]
    c.execute('SELECT elo FROM players where uname=?', (clients[1].uname,))
    clients[1].score = c.fetchone()[0]




    # Create list of actors
    actors = [player1, player2]

    stateCounter = 0
    timerEnd = time.time()

    winner = None

    # Main Game Loop
    while True:
        frameStart = time.time()
        if gameState == stateGloat:
            if time.time() >= timerEnd:
                message = '<message><event type="gameStart" '
                message += 'player="1" '
                message += 'player1Name="' + clients[0].uname + '" '
                message += 'player1Score="' + str(clients[0].score) + '" '
                message += 'player1Lives="' + str(clients[0].actor.health) + '" '
                message += 'player2Name="' + clients[1].uname + '" '
                message += 'player2Score="' + str(clients[1].score) + '" '
                message += 'player2Lives="' + str(clients[1].actor.health) + '" '
                message += ' /></message>'
                clients[0].conn.send(frameMessage(message))
                message = '<message><event type="gameStart" '
                message += 'player="2" '
                message += 'player1Name="' + clients[0].uname + '" '
                message += 'player1Score="' + str(clients[0].score) + '" '
                message += 'player1Lives="' + str(clients[0].actor.health) + '" '
                message += 'player2Name="' + clients[1].uname + '" '
                message += 'player2Score="' + str(clients[1].score) + '" '
                message += 'player2Lives="' + str(clients[1].actor.health) + '" '
                message += ' /></message>'
                clients[1].conn.send(frameMessage(message))

                reset(actors)
                timerEnd = time.time()
                gameState = statePause
                stateCounter = 0

                if player1.health <= 0:
                    winner = clients[1]
                    gameState = stateEnd
                if player2.health <= 0:
                    winner = clients[0]
                    gameState = stateEnd

        elif gameState == statePause:
            if time.time() > timerEnd:
                if stateCounter is 0:
                    clients[0].conn.send(frameMessage('<message><event type="setScrollText" content="3" /></message>'))
                    clients[1].conn.send(frameMessage('<message><event type="setScrollText" content="3" /></message>'))
                    timerEnd = time.time() + 1
                    stateCounter += 1
                elif stateCounter is 1:
                    clients[0].conn.send(frameMessage('<message><event type="setScrollText" content="2" /></message>'))
                    clients[1].conn.send(frameMessage('<message><event type="setScrollText" content="2" /></message>'))
                    timerEnd = time.time() + 1
                    stateCounter += 1
                elif stateCounter is 2:
                    clients[0].conn.send(frameMessage('<message><event type="setScrollText" content="1" /></message>'))
                    clients[1].conn.send(frameMessage('<message><event type="setScrollText" content="1" /></message>'))
                    timerEnd = time.time() + 1
                    stateCounter += 1
                elif stateCounter is 3:
                    clients[0].conn.send(frameMessage('<message><event type="setScrollText" content="FIGHT!" /></message>'))
                    clients[1].conn.send(frameMessage('<message><event type="setScrollText" content="FIGHT!" /></message>'))
                    gameState = statePlay
                    stateCounter = 0
                    timerEnd = time.time() + 1
        elif gameState == statePlay:
            if time.time() > timerEnd:
                if stateCounter is 0:
                    clients[0].conn.send(
                        frameMessage('<message><event type="setScrollText" content="" /></message>'))
                    clients[1].conn.send(
                        frameMessage('<message><event type="setScrollText" content="" /></message>'))
                    stateCounter += 1
        elif gameState == stateEnd:
            print 'game over'
            #Calculate elo change, update database, send message to clients, and end
            o1 = clients[0].score
            o2 = clients[1].score
            r1 = o1
            r2 = o2
            R1 = math.pow(10, r1 / 400)
            R2 = math.pow(10, r1 / 400)
            E1 = R1 / (R1 + R2)
            E2 = R2 / (R1 + R2)
            if winner == clients[0]:
                S1 = 0
                S2 = 1
            else:
                S1 = 1
                S2 = 0
            r1 = r1 - 32 * (S1 - E1)
            r2 = r2 - 32 * (S2 - E2)
            c.execute('UPDATE players SET elo=? WHERE uname=?', (r1, clients[0].uname))
            c.execute('UPDATE players SET elo=? WHERE uname=?', (r2, clients[1].uname))
            db.commit()
            message = '<message><event type="gameOver" '
            message += 'score="' + str(r1) + '" '
            message += 'scoreDif="' + str(r1 - o1) + '" '
            message += 'winner = "' + str(winner.actor.id) + '" '
            message += '/></message>'
            clients[0].conn.send(frameMessage(message))
            message = '<message><event type="gameOver" '
            message += 'score="' + str(r2) + '" '
            message += 'scoreDif="' + str(r2 - o2) + '" '
            message += 'winner = "' + str(winner.actor.id) + '" '
            message += '/></message>'
            clients[1].conn.send(frameMessage(message))
            clients[0].state = "loggedin"
            clients[1].state = "loggedin"
            time.sleep(2)
            break;



        # Applay AI function to AI actors
        for actor in actors:
            if actor.isAI:
                AIthink(actor)

        # State Machine
        if gameState == statePlay or gameState == stateGloat:

            # Apply input from clients to actors
            for client in clients:
                if client.state == 'disconnected':
                    print 'a client left'
                for message in client.messages:
                    for child in message:
                        if child.tag == 'input':
                            client.actor.input_x = float(child.attrib['axis_x'])
                            client.actor.input_attack = client.button_attack = int(child.attrib['button_attack'])
                del client.messages[:]

            # Update actors
            for entity in actors:
                entity.trigger = ''
                # Allow the entity to attack if cooldown is off
                if entity.input_attack == 1:
                    #Begin the attack and set the cooldown
                    entity.trigger = 'attack'
                    entity.attackTimer = entity.attackLength
                    entity.attackCooldown = entity.attackRate
                    entity.input_attack = 0
                # If the entity is attacking, move it according to its attack speed
                if entity.attackTimer > 0:
                    entity.position += entity.attackSpeed * entity.attackDirection
                # If the entity is not attacking, move it according to its move speed
                else:
                    tempSpeed = entity.speed
                    # Adjust brightness and speed based on attack cooldown. actors are slower and dimmer after attacking.
                    if entity.attackCooldown > 0:
                        tempSpeed = (1.0 - (entity.attackCooldown / entity.attackRate)) + 0.2
                        tempSpeed = min(tempSpeed, entity.speed)
                    if entity.dead is True:
                        tempSpeed = 0
                    # Move the entity

                    entity.position += entity.input_x * tempSpeed
                    # Determine what direction the entity would attack in after moving
                    if entity.input_x < 0: entity.attackDirection = -1
                    if entity.input_x > 0: entity.attackDirection = 1
                # Decrement the entity's counters
                entity.attackTimer -= frameLength
                entity.attackCooldown -= frameLength
                entity.AIattackCooldown -= frameLength
                # Clamp the entity onto the playing field
                entity.position = max(min(entity.position, 100), 0)
            # Check for collision
            if gameState == statePlay:
                if abs(actors[1].position - actors[0].position) < 1:
                    hit = False
                    # Check if either entity was attacking while the other was not
                    if (actors[0].attackTimer < 0) and (actors[1].attackTimer > 0):
                        hit = True # Register the hit
                        actors[0].health -= 1
                        actors[0].dead = True
                        for client in clients:
                            client.conn.send(frameMessage('<message><event type="death" id="1" /></message>'))
                    elif (actors[1].attackTimer < 0) and (actors[0].attackTimer > 0):
                        hit = True # Register the hit
                        actors[1].health -= 1
                        actors[1].dead = True
                        for client in clients:
                            client.conn.send(frameMessage('<message><event type="death" id="2" /></message>'))
                    # If an entity was hit, display their color, reset them, and wait 2 seconds
                    if hit is True:

                        print 'someone was hit'
                        gameState = stateGloat
                        stateCounter = 0

                        timerEnd = time.time() + 2

        # Send frame to the clients
        deadClient = 0
        for client in clients:
            if client.connected is True:
                message = '<message>'
                for actor in actors:
                    message += '<actor id="' + str(actor.id) + '" '
                    message += 'positionX="' + str(actor.position) + '" '
                    message += 'direction="' + str(actor.attackDirection) + '" '
                    if actor.trigger != '':
                        message += 'trigger="' + actor.trigger + '" '
                    message += '/>'
                message += '</message>'
                try:
                    client.conn.send(frameMessage(message))
                except socket.error:
                    deadClient = client
        if deadClient is not 0:
            clients.remove(deadClient)
        #print 'Frame Processing Time: ' + str(time.time() - frameStart)
        #Wait until the next frame
        time.sleep(frameLength)

if __name__ == "__main__":
    run()