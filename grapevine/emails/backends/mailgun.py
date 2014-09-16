# Sys
import json
import requests

try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO

# Django
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend
from django.core.mail.message import sanitize_address

# Local
# from core.utils import requests


class MailgunAPIError(Exception):
    pass


class EmailBackend(BaseEmailBackend):
    """A Django Email backend that uses mailgun. Inspiration: https://github.com/bradwhittington/django-mailgun
    """

    def __init__(self, fail_silently=False, *args, **kwargs):
        access_key, server_name = (kwargs.pop('access_key', None),
                                   kwargs.pop('server_name', None))

        super(EmailBackend, self).__init__(
                        fail_silently=fail_silently,
                        *args, **kwargs)

        try:
            self._access_key = access_key or getattr(settings, 'MAILGUN_ACCESS_KEY')
            self._server_name = server_name or getattr(settings, 'MAILGUN_SERVER_NAME')
        except AttributeError:
            if fail_silently:
                self._access_key, self._server_name = None
            else:
                raise

        self._api_url = "https://api.mailgun.net/v2/%s/" % self._server_name

    def open(self):
        """Stub for open connection, all sends are done over HTTP POSTs
        """
        pass

    def close(self):
        """Close any open HTTP connections to the API server.
        """
        pass

    def _send(self, email_message):
        """A helper method that does the actual sending."""
        if not email_message.recipients():
            return False
        from_email = sanitize_address(email_message.from_email, email_message.encoding)
        recipients = [sanitize_address(addr, email_message.encoding)
                      for addr in email_message.recipients()]

        try:
            self.r = requests.\
                post(self._api_url + "messages.mime",
                     auth=("api", self._access_key),
                     data={
                            "to": ", ".join(recipients),
                            "from": from_email,
                         },
                     files={
                            "message": StringIO(email_message.message().as_string()),
                         }
                     )
        except:
            if not self.fail_silently:
                raise
            return False

        if self.r.status_code != 200:
            failure_dict = json.loads(self.r.content)
            failure_dict['status'] = self.r.status_code
            self.failure_reason = json.dumps(failure_dict)
            if not self.fail_silently:
                raise MailgunAPIError(self.r)
            return False

        return True

    def send_messages(self, email_messages):
        """Sends one or more EmailMessage objects and returns the number of
        email messages sent.
        """
        if not email_messages:
            return

        num_sent = 0
        for message in email_messages:
            if self._send(message):
                num_sent += 1

        return num_sent