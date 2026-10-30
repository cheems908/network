#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import socket
import sys


def handleRequest(tcpSocket):
	# 1. Receive request message from the client on connection socket
	# 2. Extract the path of the requested object from the message (second part of the HTTP header)
	# 3. Read the corresponding file from disk
	# 4. Store in temporary buffer
	# 5. Send the correct HTTP response error
	# 6. Send the content of the file to the socket
	# 7. Close the connection socket 
	pass # Remove/replace when function is complete

def startServer(serverAddress, serverPort):
	# 1. Create server socket
	# 2. Bind the server socket to server address and server port
	# 3. Continuously listen for connections to server socket
	# 4. When a connection is accepted, call handleRequest function, passing new connection socket (see https://docs.python.org/3/library/socket.html#socket.socket.accept)
	# 5. Close server socket
	pass # Remove/replace when function is complete


startServer("", 8000)
