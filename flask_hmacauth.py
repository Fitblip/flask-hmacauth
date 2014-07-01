"""
    flask.ext.hmacauth
    ---------------

    This module provides HMAC-based authentication and authorization for
    Flask. It lets you work with reuests in a database-independent manner.

initiate the HmacManager with a app and set account ID, signature and timestamp
"""

from flask import current_app, request, abort
from functools import update_wrapper
import hmac
import hashlib
import datetime
import urlparse
import random
import string

#simple macros where x is a request object
GET_TIMESTAMP = lambda request_obj: request_obj.values.get('TIMESTAMP')
GET_ACCOUNT   = lambda request_obj: request_obj.values.get('ACCOUNT_ID')
GET_SIGNATURE = lambda request_obj: request_obj.headers.get('X-Auth-Signature')


class HmacManager(object):
    """
    This object is used to hold the settings for authenticating requests.  Instances of
    :class:`HmacManager` are not bound to specific apps, so you can create one in the
    main body of your code and then bind it to your app in a factory function.
    """
    def __init__(self, account_broker, app=None, account_id=GET_ACCOUNT, signature=GET_SIGNATURE,
                 timestamp=GET_TIMESTAMP, valid_time=5, digest=hashlib.sha1):
        """
        :param app Flask application container
        :param account_broker AccountBroker object
        :param account_id :type callable that takes a request object and :returns the Account ID (default
            ACCOUNT_ID parameter in the query string or POST body)
        :param signature :type callable that takes a request object and :returns the signature value (default
            X-Auth-Signature header)
        :param timestamp :type callable that takes a request object and :returns the timestamp (default
            TIMESTAMP parameter in the query string or POST body)
        :param valid_time :type integer, number of seconds a timestamp remains valid (default 20)
        :param digest hashlib hash :type to be used in the signature (default sha1)
        """

        self._account_id     = account_id
        self._signature      = signature
        self._timestamp      = timestamp
        self._account_broker = account_broker
        self._valid_time     = valid_time
        self._digest         = digest

        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        app.hmac_manager = self

    def is_authorized(self, request_obj, required_rights):
        try:
            timestamp = self._timestamp(request_obj)
            assert timestamp is not None
        except:
            #TODO: add logging
            return False

        ts = datetime.datetime.fromtimestamp(float(timestamp))

        #is the timestamp valid?
        if ts < datetime.datetime.now()-datetime.timedelta(seconds=self._valid_time) \
                or ts > datetime.datetime.now():
            #TODO: add logging
            return False

        #do we have an account ID in the request?
        try:
            account_id = self._account_id(request_obj)
        except:
            #TODO: add logging
            return False

        #do we have a secret and rights for this account?
        #implicitly, does this account exist?
        secret = self._account_broker.get_secret(account_id)
        if secret is None:
            #TODO: add logging
            return False

        #Is the account active, valid, etc?
        if not self._account_broker.is_active(account_id):
            #TODO: add logging
            return False

        #hash the request URL and Body
        hasher = hmac.new(secret, digestmod=self._digest)
        #TODO: do we need encode() here?
        url = urlparse.urlparse(request.url.encode())
        #TODO: hacky.  what about POSTs without a query string?
        hasher.update(url.path + "?" + url.query)
        if request.method == "POST":
            hasher.update(request.body)
        calculated_hash = hasher.hexdigest()

        try:
            sent_hash = self._signature(request_obj)
        except:
            #TODO: add logging
            return False

        #compare to what we got as the sig
        if not calculated_hash == sent_hash:
            #TODO: add logging
            return False

        #ensure this account has the required rights
        #TODO: add logging
        if required_rights is not None:
            if isinstance(required_rights, list):
                return self._account_broker.has_rights(account_id, required_rights)
            else:
                return self._account_broker.has_rights(account_id, [required_rights])

        return True

class BaseAccountBroker(object):
    def __init__(self):
        pass

    def is_active(self, account):
        # returns True if account_id is active (for whatever definition you want
        # to define for active), otherwise returns False.
        raise NotImplementedError("You need to define an is_active method on your class!")

    def get_secret(self, account):
        # returns a string secret given an account ID.  If the account does not exist, returns None
        raise NotImplementedError("You need to define an get_secret method on your class!")

    def has_rights(self, account, rights):
        # returns True if account_id has all of the rights in the list rights, otherwise returns False.  Returns False
        # if the account does not exist.
        raise NotImplementedError("You need to define an has_rights method on your class!")

    @staticmethod
    def generate_secret_key():
        # Helper to generate good secret keys (32 characther alnum)
        secret_key = ""
        for i in range(32):
            secret_key += random.choice(string.ascii_letters + string.digits)
        return secret_key

    def __repr__(self):
        return "<%s>" % (self.__class__.__name__)

class DictAccountBroker(BaseAccountBroker):
    """
    Default minimal implementation of an AccountBroker.  This implementation maintains
    a dict in memory with structure:
    {
        account_id:
            {
                secret: "some secret string",
                rights: ["someright", "someotherright"],
            },
        ...
    }
    Your implementation can use whatever backing store you like as long as you provide
    the following methods:

    get_secret(account_id) - returns a string secret given an account ID.  If the account does not exist, returns None
    has_rights(account_id, rights) - returns True if account_id has all of the rights in the list
        rights, otherwise returns False.  Returns False if the account does not exist.
    is_active(account_id) - returns True if account_id is active (for whatever definition you want
        to define for active), otherwise returns False.
    """

    def __init__(self, accounts=None):
        super(DictAccountBroker, self).__init__()
        if accounts is None:
            self.accounts = {}
        else:
            self.accounts = accounts

    #TODO: test
    def add_accounts(self, accounts):
        self.accounts.update(accounts)

    #TODO: test
    def del_accounts(self, accounts):
        if isinstance(accounts, list):
            for i in accounts:
                del self.accounts[i]
        else:
            del self.accounts[accounts]

    def get_secret(self, account):
        try:
            secret = self.accounts[account]["secret"]
        except KeyError:
            return None
        return secret

    def has_rights(self, account, rights):
        try:
            account_rights = self.accounts[account]["rights"]
        except KeyError:
            return False
        if set(rights).issubset(account_rights):
            return True
        return False

    def is_active(self, account):
        if account in self.accounts:
            return True
        return False


class StaticAccountBroker(BaseAccountBroker):
    """
        A very basic account broker example. Only checks against one secret, with no account names or roles
    """

    #TODO: this doesn't work?
    GET_ACCOUNT = lambda x: "dummy"

    def __init__(self, secret=None):
        super(StaticAccountBroker, self).__init__()
        if secret is None:
            raise ValueError("you must provide a value for 'secret'")
        self._secret = secret

    def is_active(self, account):
        return True

    def get_secret(self, account):
        return self._secret

    def has_rights(self, account, rights):
        return True


def hmac_auth(rights=None):
    def decorator(f):
        def wrapped_function(*args, **kwargs):
            if current_app.hmac_manager.is_authorized(request, rights):
                return f(*args, **kwargs)
            else:
                #TODO: make this custom, maybe a current_app.hmac_manager.error() call?
                abort(403)
        return update_wrapper(wrapped_function, f)
    return decorator