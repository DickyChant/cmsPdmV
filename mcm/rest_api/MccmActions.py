import flask
import time

import json
from json_layer.chained_request import ChainedRequest
from rest_api.RestAPIMethod import DeleteRESTResource, RESTResource
from couchdb_layer.mcm_database import database as Database
from json_layer.mccm import MccM
from json_layer.user import Role, User
from json_layer.chained_campaign import ChainedCampaign
from json_layer.request import Request
from tools.locker import locker
from tools.locator import locator
from tools.communicator import Communicator
from tools.settings import Settings
from tools.priority import block_to_priority


class CreateMccm(RESTResource):

    @RESTResource.ensure_role(Role.MC_CONTACT)
    def put(self):
        """
        Create the mccm with the provided json content
        """
        data = json.loads(flask.request.data)
        mccm = MccM(data)
        pwg = mccm.get_attribute('pwg').upper()
        user = User()
        if pwg not in user.get_user_pwgs():
            username = user.get_username()
            return {'results': False,
                    'message': 'User %s is not allowed to create tickets for %s' % (username, pwg)}

        possible_pwgs = Settings.get('pwg')
        if pwg not in possible_pwgs:
            self.logger.error('Bad PWG: %s', pwg)
            return {'results': False,
                    'message': 'Bad PWG "%s"' % (pwg)}

        duplicates = mccm.get_duplicate_requests()
        if duplicates:
            return {'results': False,
                    'message': 'Duplicated requests: %s' % (', '.join(duplicates))}

        mccm_db = Database('mccms')
        # Needed for prepid
        meeting_date = MccM.get_meeting_date()
        meeting_date_full = meeting_date.strftime('%Y-%m-%d')
        meeting_date_short = meeting_date.strftime('%Y%b%d')
        mccm.set_attribute('meeting', meeting_date_full)
        mccm.set_attribute('pwg', pwg) # Uppercase
        prepid_part = '%s-%s' % (pwg, meeting_date_short)
        with locker.lock('create-ticket-%s' % (prepid_part)):
            prepid = mccm_db.get_next_prepid(prepid_part, [meeting_date_full, pwg])
            mccm.set_attribute('prepid', prepid)
            mccm.set_attribute('_id', prepid)
            mccm.update_history({'action': 'created'})
            if mccm_db.save(mccm.json()):
                return {'results': True,
                        'prepid': prepid}

        return {'results': False,
                'message': 'MccM ticket could not be created'}


class UpdateMccm(RESTResource):

    @RESTResource.ensure_role(Role.MC_CONTACT)
    def post(self):
        """
        Updating a MccM with an updated dictionary
        """
        data = json.loads(flask.request.data)
        if '_rev' not in data:
            return {'results': False,
                    'message': 'No revision provided'}

        try:
            mccm = MccM(data)
        except Exception as ex:
            return {'results': False,
                    'message': str(ex)}

        prepid = mccm.get_attribute('prepid')
        if not prepid:
            self.logger.error('Invalid prepid "%s"', prepid)
            return {'results': False,
                    'message': 'Invalid prepid "%s"' % (prepid)}

        pwg = mccm.get_attribute('pwg').upper()
        user = User()
        if pwg not in user.get_user_pwgs():
            username = user.get_username()
            return {'results': False,
                    'message': 'User %s is not allowed to edit tickets for %s' % (username, pwg)}

        mccm_db = Database('mccms')
        mccm_json = mccm_db.get(prepid)
        if not mccm_json:
            self.logger.error('Cannot update, %s does not exist', prepid)
            return {'results': False,
                    'message': 'Cannot update, "%s" does not exist' % (prepid)}

        duplicates = mccm.get_duplicate_requests()
        if duplicates:
            return {'results': False,
                    'message': 'Duplicated requests: %s' % (', '.join(duplicates))}

        old_mccm = MccM(mccm_json)
        # Find what changed
        for (key, editable) in old_mccm.get_editable().items():
            old_value = old_mccm.get_attribute(key)
            new_value = mccm.get_attribute(key)
            if not editable and old_value != new_value:
                message = 'Not allowed to change "%s": "%s" -> "%s' % (key, old_value, new_value)
                self.logger.error(message)
                return {'results': False,
                        'message': message}

        if set(old_mccm.get_request_list()) != set(mccm.get_request_list()):
            self.logger.info('Request list changed, recalculating total events')
            mccm.update_total_events()

        difference = self.get_obj_diff(old_mccm.json(),
                                       mccm.json(),
                                       ('history', '_rev'))
        if not difference:
            return {'results': True}

        difference = ', '.join(difference)
        mccm.update_history('update', difference)

        # Save to DB
        if not mccm_db.update(mccm.json()):
            self.logger.error('Could not save MccM %s to database', prepid)
            return {'results': False,
                    'message': 'Could not save MccM %s to database' % (prepid)}

        return {'results': True}


class DeleteMccm(DeleteRESTResource):

    def delete_check(self, obj):
        if obj.get_attribute('status') == 'done':
            raise Exception('Cannot delete a ticket that is done')

        mccm_id = obj.get('prepid')
        # User info
        user = User()
        user_role = user.get_role()
        self.logger.info('User %s (%s) is trying to delete %s',
                         user.get_username(),
                         user_role,
                         mccm_id)
        if user_role < Role.PRODUCTION_MANAGER:
            username = user.get_username()
            history = obj.get_attribute('history')
            owner = None
            owner_name = None
            if history:
                for history_entry in history:
                    if history_entry['action'] == 'created':
                        owner = history_entry['updater']['author_username']
                        owner_name = history_entry['updater']['author_name']

            if not owner:
                raise Exception('Could not get owner of the ticket')

            if owner != username:
                raise Exception('Only the owner %s is allowed to delete the ticket' % (owner_name))

        return super().delete_check(obj)

    @RESTResource.ensure_role(Role.MC_CONTACT)
    def delete(self, prepid):
        """
        Delete a MccM ticket
        """
        return self.delete_object(prepid, MccM)


class GetMccm(RESTResource):

    def get(self, prepid):
        """
        Retrieve the MccM for given id
        """
        return {'results': MccM.get_database().get(prepid)}


class CancelMccm(RESTResource):

    @RESTResource.ensure_role(Role.MC_CONTACT)
    @RESTResource.request_with_json
    def post(self, data):
        """
        Cancel the MccM tickets
        Does not delete it but put the status as cancelled.
        """
        user = User()
        def cancel_ticket(mccm):
            status = mccm.get_attribute('status')
            if status == 'done':
                raise Exception("Ticket is done, cannot be cancelled")

            if user.get_role() < Role.PRODUCTION_MANAGER:
                user_pwgs = user.get_user_pwgs()
                ticket_pwg = mccm.get_attribute("pwg")
                if ticket_pwg not in user_pwgs:
                    raise Exception("You cannot cancel ticket with different PWG than yours")

            if status == 'new':
                mccm.set_attribute('status', 'cancelled')
                mccm.update_history('cancel')
            elif status == 'cancelled':
                mccm.set_attribute('status', 'new')
                mccm.update_history('uncancel')

        return self.do_multiple_items(data['prepid'], MccM, cancel_ticket)


class NotifyMccm(RESTResource):

    @RESTResource.ensure_role(Role.PRODUCTION_MANAGER)
    def put(self):
        """
        Sends the prodived posted text to the users who acted on MccM ticket
        """
        data = json.loads(flask.request.data)
        # Message
        message = data['message'].strip()
        if not message:
            return {'results': False,
                    'message': 'No message'}

        # Prepid
        prepid = data['prepid']
        mccm_db = Database('mccms')
        mccm_json = mccm_db.get(prepid)
        if not mccm_json:
            return {"results": False,
                    "message": "Could not find %s" % (prepid)}

        # Subject
        subject = data.get('subject', 'Communication about %s' % (prepid)).strip()
        mccm = MccM(mccm_json)
        mccm.get_current_user_role_level()
        mccm.notify(subject, message, accumulate=False)
        return {"results": True}


class GetEditableMccmFields(RESTResource):

    def get(self, prepid):
        """
        Retrieve the fields that are currently editable for a given mccm
        """
        return {"results": MccM.fetch(prepid).get_editable()}


class GenerateChains(RESTResource):

    @RESTResource.ensure_role(Role.MC_CONTACT)
    @RESTResource.request_with_json
    def post(self, data):
        """
        Operate the chaining for a given MccM document id
        """
        # Skip existing ones?
        skip_existing = flask.request.args.get('skip_existing', 'False').lower() == 'true'
        # Allow duplicated chained requests?
        allow_duplicates = flask.request.args.get('allow_duplicates', 'False').lower() == 'true'

        prepid = data['prepid']
        lock = locker.lock(prepid)
        if lock.acquire(blocking=False):
            try:
                res = self.generate(prepid, skip_existing, allow_duplicates)
            except Exception as ex:
                import traceback
                self.logger.error(traceback.format_exc())
                res = {'results': False,
                       'prepid': prepid,
                       'message': str(ex)}
            finally:
                lock.release()
            return res
        else:
            return {'results': False,
                    'prepid': prepid,
                    'message': 'Ticket is already being operated on'}

    def generate(self, prepid, skip_existing, generate_all):
        mccm = MccM.fetch(prepid)
        status = mccm.get_attribute('status')
        if status != 'new' and not skip_existing:
            raise Exception('Status is "%s", expecting "new"' % (status))

        block = mccm.get_attribute('block')
        if not block:
            raise Exception('Priority block not selected')

        chained_campaign_prepids = mccm.get_attribute('chains')
        if not chained_campaign_prepids:
            raise Exception('No chained campaigns selected')

        # Make a set just to be sure they are unique
        request_prepids = sorted(list(set(mccm.get_request_list())))
        if not request_prepids:
            raise Exception('No requests selected')

        repetitions = mccm.get_attribute('repetitions')
        if not repetitions:
            raise Exception('Number of repetitions "%s" is invalid' % (repetitions))

        # Chained campaigns of ticket
        chained_campaigns = ChainedCampaign.get_database().bulk_get(chained_campaign_prepids)
        not_found = [p for c, p in zip(chained_campaigns, chained_campaign_prepids) if not c]
        if not_found:
            raise Exception('Could not find %s' % (not_found[0]))

        chained_campaigns = [ChainedCampaign(c) for c in chained_campaigns]
        # Requests of ticket
        requests = Request.get_database().bulk_get(request_prepids)
        not_found = [p for c, p in zip(requests, request_prepids) if not c]
        if not_found:
            raise Exception('Could not find %s' % (not_found[0]))

        requests = [Request(r) for r in requests]
        # Root campaigns of chained campaigns
        root_campaigns = {}
        for chained_campaign in chained_campaigns:
            root_campaign = chained_campaign.campaign(0)
            root_campaigns.setdefault(root_campaign, []).append(chained_campaign)

        # Check requests
        chained_campaigns_for_requests = {}
        chained_request_db = ChainedRequest.get_database()
        for request in requests:
            request_prepid = request.get_attribute('prepid')
            request_campaign = request.get_attribute('member_of_campaign')
            request_pwg = request.get_attribute('pwg')
            if request_campaign not in root_campaigns:
                raise Exception('"%s" campaign is not in given chains' % (request_prepid))

            if request.get_attribute('flown_with'):
                raise Exception('"%s" is in the middle of the chain' % (request_prepid))

            chained_campaigns_for_request = [c for c in root_campaigns[request_campaign]]
            if not generate_all:
                query = {'member_of_campaign': [c.get('prepid') for c in chained_campaigns_for_request],
                         'contains': request_prepid,
                         'pwg': request_pwg}
                duplicates = [c['member_of_campaign'] for c in chained_request_db.search(query, limit=-1)]
                if duplicates:
                    if skip_existing:
                        # Remove duplicates
                        duplicates = set(duplicates)
                        chained_campaigns_for_request = [c for c in chained_campaigns_for_request if c['prepid'] not in duplicates]
                    else:
                        raise Exception('Chain with request "%s" and chained campaign "%s" '
                                        'already exist.' % (request_prepid, duplicates[0]))

            chained_campaigns_for_requests[request_prepid] = chained_campaigns_for_request

        results = []
        generated_chains = mccm.get_attribute('generated_chains')
        for request in requests:
            request_prepid = request.get_attribute('prepid')
            chained_campaigns = chained_campaigns_for_requests[request_prepid]
            self.logger.info('Generating chained requests for %s, chained campaigns - %s',
                             request_prepid,
                             len(chained_campaigns))
            for chained_campaign in chained_campaigns:
                for _ in range(repetitions):
                    chained_request_prepid = self.generate_chained_request(mccm, request, chained_campaign)
                    generated_chains[chained_request_prepid] = []
                    mccm.set_attribute("generated_chains", generated_chains)
                    mccm.reload(save=True)
                    results.append(chained_request_prepid)
                    # A small delay to not crash DB
                    time.sleep(0.05)

        if not results:
            return {"prepid": prepid,
                    "results": True,
                    "message": 'Everything went fine, but nothing was generated'}

        mccm.set('status', 'done')
        mccm.update_history('generate')
        if not mccm.save():
            return {'prepid': prepid,
                    'results': False,
                    'message': 'Could not save ticket to the database'}

        return {'prepid': prepid,
                'results': results,
                'message': ''}

    def generate_chained_request(self, mccm, root_request, chained_campaign):
        # Generate the chained request
        chained_request = chained_campaign.generate_request(root_request)
        root_request.reload(save=False)
        chained_request_prepid = chained_request.get_attribute('prepid')
        # Updates from the ticket
        block = mccm.get_attribute('block')
        priority = block_to_priority(block)
        chained_request.set('priority', priority)
        if not chained_request.reload():
            raise Exception('Unable to save chained request %s' % (chained_request_prepid))

        return chained_request_prepid


class MccMReminderGenContacts(RESTResource):

    @RESTResource.ensure_role(Role.ADMINISTRATOR)
    def get(self):
        """
        Send a reminder to the generator conveners about "new" MccM tickets that
        don't have all requests "defined"
        """
        mccm_db = Database('mccms')
        mccm_jsons = mccm_db.search({'status': 'new'}, page=-1)
        if not mccm_jsons:
            return {"results": True,
                    "message": "No new tickets, what a splendid day!"}

        l_type = locator()
        com = Communicator()
        self.logger.info('Found %s new MccM tickets', len(mccm_jsons))
        # Quickly filter-out no request, no chain and 0 block ones
        mccm_jsons = [m for m in mccm_jsons if m['requests'] and m['chains'] and m['block']]
        mccm_jsons = sorted(mccm_jsons, key=lambda x: x['prepid'])
        mccms = [MccM(mccm_json) for mccm_json in mccm_jsons]
        # Get all defined but not approved requests
        not_defined_requests = {}
        for mccm in mccms:
            prepid = mccm.get_attribute('prepid')
            not_defined_requests[prepid] = mccm.get_not_defined()

        # Only tickets that have all requests at least defined, but not all
        # approved
        mccms = [mccm for mccm in mccms if len(not_defined_requests[mccm.get_attribute('prepid')])]

        by_pwg = {}
        for mccm in mccms:
            pwg = mccm.get_attribute('pwg')
            by_pwg.setdefault(pwg, []).append(mccm)

        subject_template = 'Gentle reminder about %s %s tickets'
        message_template = 'Dear GEN Contacts of %s,\n\n'
        message_template += 'Below you can find a list of MccM tickets where not all requests are '
        message_template += 'in "defined" status.\n'
        message_template += 'Please check them and once all are defined, present them in MccM or '
        message_template += 'cancel/delete tickets if they are no longer needed.\n\n'
        base_url = l_type.baseurl()
        contacts = self.get_contacts_by_pwg()
        for pwg, pwg_mccms in by_pwg.items():
            recipients = contacts.get(pwg)
            if not recipients:
                self.logger.info('No recipients for %s, will not remind about tickets', pwg)
                continue

            subject = subject_template % (len(pwg_mccms), pwg)
            message = message_template % (pwg)
            for mccm in pwg_mccms:
                prepid = mccm.get_attribute('prepid')
                not_defined = len(not_defined_requests[prepid])
                total = len(mccm.get_request_list())
                message += 'Ticket: %s (%s/%s request(s) are not defined)\n' % (prepid,
                                                                                    not_defined,
                                                                                    total)
                message += '%smccms?prepid=%s\n\n' % (base_url, prepid)

            message += 'You received this email because you are listed as GEN contact of %s.\n' % (pwg)
            com.sendMail(recipients, subject, message)

        return {"results": True,
                "message": [mccm.get_attribute('prepid') for mccm in mccms]}


    def get_contacts_by_pwg(self):
        """
        Get list of generator contact emails by PWG
        """
        user_db = Database('users')
        generator_contacts = user_db.query_view('role', 'generator_contact', page_num=-1)
        by_pwg = {}
        for contact in generator_contacts:
            for pwg in contact.get('pwg', []):
                by_pwg.setdefault(pwg, []).append(contact['email'])

        return by_pwg


class MccMReminderProdManagers(RESTResource):

    @RESTResource.ensure_role(Role.ADMINISTRATOR)
    def get(self):
        """
        Send a reminder to the production managers about "new" MccM tickets that
        have all requests "approved"
        """
        mccm_db = Database('mccms')
        mccm_jsons = mccm_db.search({'status': 'new'}, page=-1)
        if not mccm_jsons:
            return {"results": True,
                    "message": "No new tickets, what a splendid day!"}

        l_type = locator()
        com = Communicator()
        self.logger.info('Found %s new MccM tickets', len(mccm_jsons))
        # Quickly filter-out no request, no chain and 0 block ones
        mccm_jsons = [m for m in mccm_jsons if m['requests'] and m['chains'] and m['block']]
        def sort_attr(mccm):
            return (mccm['meeting'], 100000 - int(mccm['prepid'].split('-')[-1]))

        def comma_separate_thousands(number):
            return '{:,}'.format(int(number))

        mccm_jsons = sorted(mccm_jsons, key=sort_attr, reverse=True)
        mccms = [MccM(mccm_json) for mccm_json in mccm_jsons]
        mccms = [mccm for mccm in mccms if mccm.all_requests_approved()]
        self.logger.info('Have %s MccM tickets after filters', len(mccms))
        # Email
        subject = 'Gentle reminder about %s approved tickets' % (len(mccms))
        message = 'Dear Production Managers,\n\n'
        message += 'Below you can find a list of MccM tickets in status "new" '
        message += 'that have all requests "approved".\n'
        message += 'You can now operate on them or delete/cancel unneeded ones.\n'
        by_pwg = {}
        for mccm in mccms:
            pwg = mccm.get_attribute('pwg')
            by_pwg.setdefault(pwg, []).append(mccm)

        base_url = l_type.baseurl()
        for pwg in sorted(list(by_pwg.keys())):
            pwg_mccms = by_pwg[pwg]
            message += '\n%s (%s tickets)\n' % (pwg, len(pwg_mccms))
            for mccm in pwg_mccms:
                prepid = mccm.get_attribute('prepid')
                block = mccm.get_attribute('block')
                events = comma_separate_thousands(mccm.get_attribute('total_events'))
                message += '  Ticket: %s (block %s and %s events)\n' % (prepid, block, events)
                message += '  %smccms?prepid=%s\n\n' % (base_url, prepid)

        user_db = Database('users')
        production_managers = user_db.query_view('role', 'production_manager', page_num=-1)
        recipients = [manager['email'] for manager in production_managers]
        com.sendMail(recipients, subject, message)
        return {"results": True,
                "message": [mccm.get_attribute('prepid') for mccm in mccms]}


class MccMReminderGenConveners(RESTResource):

    @RESTResource.ensure_role(Role.ADMINISTRATOR)
    def get(self):
        """
        Send a reminder to the generator conveners about "new" MccM tickets that
        don't have all requests "approved"
        """
        mccm_db = Database('mccms')
        mccm_jsons = mccm_db.search({'status': 'new'}, page=-1)
        if not mccm_jsons:
            return {"results": True,
                    "message": "No new tickets, what a splendid day!"}

        l_type = locator()
        com = Communicator()
        self.logger.info('Found %s new MccM tickets', len(mccm_jsons))
        # Quickly filter-out no request, no chain and 0 block ones
        mccm_jsons = [m for m in mccm_jsons if m['requests'] and m['chains'] and m['block']]
        mccm_jsons = sorted(mccm_jsons, key=lambda x: x['prepid'])
        mccms = [MccM(mccm_json) for mccm_json in mccm_jsons]
        # Get all defined but not approved requests
        defined_requests = {}
        for mccm in mccms:
            prepid = mccm.get_attribute('prepid')
            defined_requests[prepid] = mccm.get_defined_but_not_approved_requests()
        # Only tickets that have all requests at least defined, but not all
        # approved
        mccms = [mccm for mccm in mccms if len(defined_requests[mccm.get_attribute('prepid')])]
        self.logger.info('Have %s MccM tickets after filters', len(mccms))
        # Email
        subject = 'Gentle reminder about %s tickets that need approval' % (len(mccms))
        message = 'Dear GEN Conveners,\n\n'
        message += 'Below you can find a list of MccM tickets in status "new" '
        message += 'that have all requests "defined", but not all "approved".\n'
        message += 'You need to check the remaining requests and approve them '
        message += 'if they are correct and were presented in a meeting.\n'
        by_meeting_pwg = {}
        for mccm in mccms:
            pwg = mccm.get_attribute('pwg')
            meeting = mccm.get_attribute('meeting')
            by_meeting_pwg.setdefault(meeting, {}).setdefault(pwg, []).append(mccm)

        base_url = l_type.baseurl()
        for meeting in sorted(list(by_meeting_pwg.keys()), reverse=True):
            by_meeting = by_meeting_pwg[meeting]
            ticket_count = sum(len(mccms) for _, mccms in by_meeting.items())
            message += '\nMeeting %s (%s tickets)\n' % (meeting, ticket_count)
            for pwg in sorted(list(by_meeting.keys())):
                pwg_mccms = by_meeting[pwg]
                message += '  %s (%s tickets)\n' % (pwg, len(pwg_mccms))
                for mccm in pwg_mccms:
                    prepid = mccm.get_attribute('prepid')
                    defined = len(defined_requests[prepid])
                    total = len(mccm.get_request_list())
                    message += '    Ticket: %s (%s/%s request(s) are not approved)\n' % (prepid,
                                                                                         defined,
                                                                                         total)
                    message += '    %smccms?prepid=%s\n\n' % (base_url, prepid)


        user_db = Database('users')
        generator_conveners = user_db.query_view('role', 'generator_convener', page_num=-1)
        recipients = [manager['email'] for manager in generator_conveners]
        com.sendMail(recipients, subject, message)
        return {"results": True,
                "message": [mccm.get_attribute('prepid') for mccm in mccms]}


class CalculateTotalEvts(RESTResource):

    @RESTResource.ensure_role(Role.MC_CONTACT)
    @RESTResource.request_with_json
    def post(self, data):
        """
        Force to recalculate total events for ticket
        """
        def recalculate(mccm):
            mccm.update_total_events()

        return self.do_multiple_items(data['prepid'], MccM, recalculate)


class CheckIfAllApproved(RESTResource):

    @RESTResource.ensure_role(Role.MC_CONTACT)
    def get(self, mccm_id):
        """
        Return whether all requests in MccM are approve-approved
        """
        mccm_db = Database('mccms')
        mccm_json = mccm_db.get(mccm_id)
        if not mccm_json:
            return {"results": False,
                    'message': '%s does not exist' % (mccm_id)}

        mccm = MccM(mccm_json)
        requests_prepids = mccm.get_request_list()
        request_db = Database('requests')
        requests = request_db.bulk_get(requests_prepids)
        requests_prepids = set(requests_prepids)
        allowed_approvals = {'approve', 'submit'}
        for request in requests:
            if not request:
                continue

            requests_prepids.remove(request['prepid'])
            if request.get('approval') not in allowed_approvals:
                return {'results': False}

        if requests_prepids:
            return {'results': False,
                    'message': 'Request(s) %s do not exist' % (', '.join(list(requests_prepids)))}

        return {'results': True}
