from rest_framework.throttling import SimpleRateThrottle


class _IpThrottle(SimpleRateThrottle):
    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class LoginRateThrottle(_IpThrottle):
    scope = "login"


class RegisterRateThrottle(_IpThrottle):
    scope = "register"
