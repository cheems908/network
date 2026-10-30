#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import socket
import os
import sys
import struct
import time
import select
import binascii  


ICMP_ECHO_REQUEST = 8 #ICMP type code for echo request messages
ICMP_ECHO_REPLY = 0 #ICMP type code for echo reply messages


def checksum(string): 
	csum = 0
	countTo = (len(string) // 2) * 2  
	count = 0

	while count < countTo:
		thisVal = string[count+1] * 256 + string[count]
		csum = csum + thisVal 
		csum = csum & 0xffffffff  
		count = count + 2
	
	if countTo < len(string):
		csum = csum + string[len(string) - 1]
		csum = csum & 0xffffffff 
	
	csum = (csum >> 16) + (csum & 0xffff)
	csum = csum + (csum >> 16)
	answer = ~csum 
	answer = answer & 0xffff 
	answer = answer >> 8 | (answer << 8 & 0xff00)

	answer = socket.htons(answer)

	return answer
	
def receiveOnePing(icmpSocket, destinationAddress, ID, timeout):
	# 1. Wait for the socket to receive a reply
	# 2. Once received, record time of receipt, otherwise, handle a timeout
	# 3. Compare the time of receipt to time of sending, producing the total network delay
	# 4. Unpack the packet header for useful information, including the ID
	# 5. Check that the ID matches between the request and reply
	# 6. Return total network delay
	pass # Remove/replace when function is complete
	
def sendOnePing(icmpSocket, destinationAddress, ID):
	# 1. Build ICMP header
	# 2. Checksum ICMP packet using given function
	# 3. Insert checksum into packet
	# 4. Send packet using socket
	# 5. Record time of sending
	pass # Remove/replace when function is complete
	
def doOnePing(destinationAddress, timeout): 
	# 1. Create ICMP socket
	# 2. Call sendOnePing function
	# 3. Call receiveOnePing function
	# 4. Close ICMP socket
	# 5. Return total network delay
	pass # Remove/replace when function is complete
	
def ping(host, timeout=1):
	# 1. Look up hostname, resolving it to an IP address
	# 2. Call doOnePing function, approximately every second
	# 3. Print out the returned delay
	# 4. Continue this process until stopped	
	pass # Remove/replace when function is complete  
	

ping("lancaster.ac.uk")

