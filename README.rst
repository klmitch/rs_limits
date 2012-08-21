========================================================
Rackspace-specific Rate Limit Preprocessor for Turnstile
========================================================

This package provides the ``rs_limits`` Python module, which contains
the ``rs_preprocess()`` preprocessor for use with Turnstile.  This
module works together with nova_limits to provide class-based rate
limiting integration with nova in the Rackspace.  To use, you must
configure the Turnstile middleware with the following configuration::

    [filter:turnstile]
    use = egg:turnstile#turnstile
    turnstile = nova_limits:NovaTurnstileMiddleware
    preprocess = rs_limits:rs_preprocess nova_limits:nova_preprocess
    redis.host = <your Redis database host>

Then, simply use the ``nova_limits:NovaClassLimit`` rate limit class
in your configuration.

The ``rs_limits:rs_preprocess()`` preprocessor derives the rate-limit
class from the "X-PP-Groups" header of the request, if present.  It
expects the database to contain a key "rs_group:<group name>" mapping
the group name to a rate-limit class; if no such key exists, the next
group name will be tried.

Note that ``rs_limits:rs_preprocess`` must be listed in the
``preprocess`` key of the configuration immediately before
``nova_limits:nova_preprocess``; additionally, both must be listed for
``nova_limits:NovaClassLimit`` to function properly.
