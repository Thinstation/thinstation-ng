#! /bin/sh

. /etc/thinstation.global

export DISPLAY=:0.0
export XAUTHORITY=/run/lightdm/$USER/xauthority

ICA_ROOT=/opt/Citrix/ICAClient
ICA_STOREBROWSE=$ICA_ROOT/util/storebrowse
LOGGERTAG="ica_receiver_clear_credentials.sh"
SESSION_ALIVEFILE=/tmp/ica_receiver_clear_credentials_session_alive
SESSION_DEADFILE=/tmp/ica_receiver_clear_credentials_session_dead

ICASTORE_ALIVEFILE=/tmp/ica_receiver_clear_credentials_store_alive

# Check if any Citrix icastore are running
if is_enabled ${ICA_RECEIVER_CLEAR_CREDENTIALS_WHEN_STORE_CLOSED} ; then
	if ps -o comm | egrep -q "icastore"; then
		# icastore is running
		if [ ! -f $ICASTORE_ALIVEFILE ]; then
			touch $ICASTORE_ALIVEFILE
		fi

	elif [ -f $ICASTORE_ALIVEFILE ] ; then
		# This section will only be run the first time we notice that all icastore have been closed.

		rm -f $ICASTORE_ALIVEFILE

		logger --stderr --tag $LOGGERTAG "Clearing the user credentials for Citrix Receiver since since all previously running Citrix icastore now has ended and ICA_RECEIVER_CLEAR_CREDENTIALS_WHEN_STORE_CLOSED is enabled."
		$ICA_STOREBROWSE --killdaemon
	fi
fi

# Check if any Citrix sessions are running
if ps -o comm | egrep -q "wfica"; then
	# A Citrix session are running
	rm -f $SESSION_DEADFILE

	# Check if it's a newly started Citrix session
	if [ ! -f $SESSION_ALIVEFILE ]; then
	
		# Create the alive file
		touch $SESSION_ALIVEFILE
	
		# Check if we shall clear the credentials as soon as the user has launched a Citrix session
		if is_enabled ${ICA_RECEIVER_CLEAR_CREDENTIALS_WHEN_SESSION_LAUNCHED} ; then
			logger --stderr --tag $LOGGERTAG "Clearing the user credentials for Citrix Receiver since we have a Citrix session running and ICA_RECEIVER_CLEAR_CREDENTIALS_WHEN_SESSION_LAUNCHED is enabled."
			$ICA_STOREBROWSE --killdaemon
		else
			logger --stderr --tag $LOGGERTAG "Detected that a Citrix session have been launched but ICA_RECEIVER_CLEAR_CREDENTIALS_WHEN_SESSION_LAUNCHED is not enabled."
		fi
	fi
elif [ -f $SESSION_ALIVEFILE ] && [ ! -f $SESSION_DEADFILE ]; then
	# This section will only be run the first time we notice that all Citrix sessions have been closed.
	
	# No Citrix session is running, kill the alive file
	rm -f $SESSION_ALIVEFILE


	# Check if we EVER shall clear the credentials after all the Citrix sessions has ended
	if [ -n "${ICA_RECEIVER_CLEAR_CREDENTIALS_AFTER_SESSION_ENDS}" ]; then

		# Check if we shall clear the credentials directly after all the Citrix sessions has ended
		if [ $((ICA_RECEIVER_CLEAR_CREDENTIALS_AFTER_SESSION_ENDS)) -eq 0 ]; then
			logger --stderr --tag $LOGGERTAG "Clearing the user credentials for Citrix Receiver since all previously running Citrix sessions now has ended and ICA_RECEIVER_CLEAR_CREDENTIALS_AFTER_SESSION_ENDS is set to 0."
			$ICA_STOREBROWSE --killdaemon
		else
			# Create a timestamp if this is the first time we run this since the sessions ended
			date +%s > $SESSION_DEADFILE
		fi
	fi


elif [ -f $SESSION_DEADFILE ] && [ -n "${ICA_RECEIVER_CLEAR_CREDENTIALS_AFTER_SESSION_ENDS}" ]; then
	# We have a deadfile (=waiting for 

	# Get the last timestamp when the processes was running
	DEADTIMESTAMP=$(cat $SESSION_DEADFILE)

	# Calculate the time difference
	TIME=$(date +%s)
	IDLE=$(expr ${TIME} - ${DEADTIMESTAMP})

	if [ ${IDLE} -gt $((ICA_RECEIVER_CLEAR_CREDENTIALS_AFTER_SESSION_ENDS)) ]; then
		logger --stderr --tag $LOGGERTAG "Clearing the user credentials for Citrix Receiver since all previously running Citrix sessions has ended for more then ${ICA_RECEIVER_CLEAR_CREDENTIALS_AFTER_SESSION_ENDS} minutes ago."
		$ICA_STOREBROWSE --killdaemon
		
		# Delete the deadfile (otherwise this will run everytime)
		rm -f $SESSION_DEADFILE
	else
		logger --stderr --tag $LOGGERTAG "Waiting for delay time ${ICA_RECEIVER_CLEAR_CREDENTIALS_AFTER_SESSION_ENDS} minutes before clearing user credentials in Citrix Receiver. No Citrix sessions have been running for the last $(($IDLE / 60)) minutes."
	fi
fi
