import smtplib
import logging

from email.message import EmailMessage
from email.utils import make_msgid, formatdate
from tools.locator import locator
import tools.settings as settings
from tools.locker import locker


class communicator:
    cache = {}
    logger = logging.getLogger("mcm_error")

    def __init__(self):
        self.from_opt = 'user'  # could be service at some point

    def flush(self, Nmin):
        res = []
        with locker.lock('accumulating_notifcations'):
            for key in self.cache.keys():
                (subject, sender, addressee) = key
                if self.cache[key]['N'] <= Nmin:
                    # flush only above a certain amount of messages
                    continue
                destination = addressee.split(', ')
                text = self.cache[key]['Text']
                msg = EmailMessage()
                msg['From'] = sender
                msg['To'] = addressee
                msg['Date'] = formatdate(localtime=True)
                new_msg_ID = make_msgid()
                msg['Message-ID'] = new_msg_ID
                msg['Subject'] = subject
                # add a signature automatically
                text += '\n\n'
                text += 'McM Announcing service'
                # self.logger.info('Sending a message from cache \n%s'% (text))
                try:
                    msg.set_content(text)
                    smtpObj = smtplib.SMTP()
                    smtpObj.connect()
                    smtpObj.sendmail(sender, destination, msg.as_string())
                    smtpObj.quit()
                    self.cache.pop(key)
                    res.append(subject)
                except Exception as e:
                    communicator.logger.error("Error: unable to send email %s", e.__class__)
            return res

    def sendMail(self,
                 destination,
                 subject,
                 text,
                 sender=None,
                 reply_msg_ID=None,
                 accumulate=False):

        if not isinstance(destination, list):
            communicator.logger.error("Cannot send email. destination should be a list of strings")
            return

        destination.sort()
        msg = EmailMessage()
        # it could happen that message are send after forking, threading and there's no current user anymore
        msg['From'] = sender if sender else 'pdmvserv@cern.ch'

        # add a mark on the subjcet automatically
        if locator().isDev():
            msg['Subject'] = '[McM-dev] ' + subject
            destination = ["pdmvserv@cern.ch"]  # if -dev send only to service account and sender
            if sender:
                destination.append(sender)
        else:
            msg['Subject'] = '[McM] ' + subject

        msg['To'] = ', '.join(destination)
        msg['Date'] = formatdate(localtime=True)
        new_msg_ID = make_msgid()
        msg['Message-ID'] = new_msg_ID

        if reply_msg_ID is not None:
            msg['In-Reply-To'] = reply_msg_ID
            msg['References'] = reply_msg_ID

        # accumulate messages prior to sending emails
        com__accumulate = settings.get_value('com_accumulate')
        force_com_accumulate = settings.get_value('force_com_accumulate')
        if force_com_accumulate or (accumulate and com__accumulate):
            with locker.lock('accumulating_notifcations'):
                # get a subject where the request name is taken out
                subject_type = " ".join(filter(lambda w: w.count('-') != 2, msg['Subject'].split()))
                addressees = msg['To']
                sendee = msg['From']
                key = (subject_type, sendee, addressees)
                if key in self.cache:
                    self.cache[key]['Text'] += '\n\n'
                    self.cache[key]['Text'] += text
                    self.cache[key]['N'] += 1
                else:
                    self.cache[key] = {'Text': text, 'N': 1}
                # self.logger.info('Got a message in cache %s'% (self.cache.keys()))
                return new_msg_ID


        # add a signature automatically
        text += '\n\n'
        text += 'McM Announcing service'

        try:
            msg.set_content(text)
            smtpObj = smtplib.SMTP()
            smtpObj.connect()
            smtpObj.sendmail(sender, destination, msg.as_string())
            smtpObj.quit()
            return new_msg_ID
        except Exception as e:
            communicator.logger.error("Error: unable to send email %s", e.__class__)
