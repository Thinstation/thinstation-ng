#! /bin/sh

. /etc/thinstation.global

LOGGERTAG="ica_receiver_config.sh"

####
# Start of Receiver clear credentials job
##

# See if we shall schedule a job to clear the users credentials in Citrix Receiver
if is_enabled ${ICA_RECEIVER_CLEAR_CREDENTIALS_WHEN_STORE_CLOSED} || is_enabled ${ICA_RECEIVER_CLEAR_CREDENTIALS_WHEN_SESSION_LAUNCHED} || [ -n "${ICA_RECEIVER_CLEAR_CREDENTIALS_AFTER_SESSION_ENDS}" ]; then
		
	# See if we shall schedule a job to clear the users credentials in Citrix Receiver
	# (cast it to an integer so if it's not defined it will return 0)
	if [ $((ICA_RECEIVER_CLEAR_CREDENTIALS_CHECK_INTERVAL)) -gt 0 ]; then
		logger --stderr --tag $LOGGERTAG "Adding ica_receiver_clear_credentials.sh with $((ICA_RECEIVER_CLEAR_CREDENTIALS_CHECK_INTERVAL)) minutes interval to crontab."

		if ! crontab -l | grep -q 'ica_receiver_clear_credentials.sh'; then
			(crontab -l || true; echo "*/$((ICA_RECEIVER_CLEAR_CREDENTIALS_CHECK_INTERVAL)) * * * * /bin/ica_receiver_clear_credentials.sh")| crontab -
		fi
	else
		logger --stderr --tag $LOGGERTAG "ICA_RECEIVER_CLEAR_CREDENTIALS_CHECK_INTERVAL is 0 although ICA_RECEIVER_CLEAR_CREDENTIALS_WHEN_STORE_CLOSED and/or ICA_RECEIVER_CLEAR_CREDENTIALS_WHEN_SESSION_LAUNCHED and/or ICA_RECEIVER_CLEAR_CREDENTIALS_AFTER_SESSION_ENDS are defined. No job and will not be added to crontab!"
	fi
else
	logger --stderr --tag $LOGGERTAG "Neither ICA_RECEIVER_CLEAR_CREDENTIALS_WHEN_STORE_CLOSED or ICA_RECEIVER_CLEAR_CREDENTIALS_WHEN_SESSION_LAUNCHED or ICA_RECEIVER_CLEAR_CREDENTIALS_AFTER_SESSION_ENDS are set, no job will be added to crontab."
fi

####
# End of Receiver clear credentials job
##
