from enum import Enum
from functools import wraps, partial
from mock import MagicMock

from nameko.extensions import DependencyProvider
from statsd import StatsClient, TCPStatsClient


class Protocols(Enum):
    tcp = 'tcp'
    udp = 'udp'


class LazyClient(object):

    """Provide an interface to `StatsClient` with a lazy client creation.
    """

    def __init__(self, **config):
        self.config = config
        self.enabled = config.pop('enabled')
        self._client = None

        protocol = self.config.pop('protocol', Protocols.udp.name)

        try:
            self.protocol = getattr(Protocols, protocol.lower())
        except AttributeError:
            raise ValueError(
                'Invalid protocol: {}'.format(protocol)
            )

    @property
    def client(self):
        if self._client is None:
            if self.protocol is Protocols.udp:
                self._client = StatsClient(**self.config)
            else:   # self.protocol is Protocols.tcp
                self._client = TCPStatsClient(**self.config)

        return self._client

    def __getattr__(self, name):
        if name in ('incr', 'decr', 'gauge', 'set', 'timing'):
            return partial(self._passthrough, name)
        else:
            message = "'{cls}' object has no attribute '{attr}'".format(
                cls=self.__class__.__name__, attr=name
            )
            raise AttributeError(message)

    def _passthrough(self, name, *args, **kwargs):
        if self.enabled:
            return getattr(self.client, name)(*args, **kwargs)

    def timer(self, *args, **kwargs):
        if self.enabled:
            return self.client.timer(*args, **kwargs)
        else:
            return MagicMock()


class StatsD(DependencyProvider):

    def __init__(self, key, name=None, *args, **kwargs):
        """
        Args:
            key (str): The key under the `STATSD` config dictionary.
            name (str): The name associated to the instance.
        """
        self._key = key
        self._name = name or ''
        super(StatsD, self).__init__(*args, **kwargs)

    def get_dependency(self, worker_ctx):
        return LazyClient(**self.config)

    def setup(self):
        self.config = self.get_config()
        return super(StatsD, self).setup()

    def get_config(self):
        return self.container.config['STATSD'][self._key]

    def timer(self, *targs, **tkwargs):

        def decorator(method):

            @wraps(method)
            def wrapper(svc, *args, **kwargs):
                dependency = getattr(svc, self._name)

                if dependency.enabled:
                    with dependency.client.timer(*targs, **tkwargs):
                        res = method(svc, *args, **kwargs)
                else:
                    res = method(svc, *args, **kwargs)

                return res

            return wrapper

        return decorator
