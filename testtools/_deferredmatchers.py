# Copyright (c) testtools developers. See LICENSE for details.

"""Matchers that operate on synchronous Deferreds.

A "synchronous" Deferred is one that does not need the reactor or any other
asynchronous process in order to fire.

Normal application code can't know when a Deferred is going to fire, because
that is generally left up to the reactor. Well-written unit tests provide fake
reactors, or don't use the reactor at all, so that Deferreds fire
synchronously.

These matchers allow you to make assertions about when and how Deferreds fire,
and about what values they fire with.
"""

# TODO: None of these are published yet. Decide where & how to make them
# public.
from functools import partial

from testtools.compat import _u
from testtools.content import TracebackContent
from testtools.matchers import Mismatch


class ImpossibleDeferredError(Exception):
    """Raised if a Deferred somehow triggers both a success and a failure."""

    def __init__(self, deferred, successes, failures):
        super(ImpossibleDeferredError, self).__init__(
            'Impossible condition on {}, got both success ({}) and '
            'failure ({})'.format(deferred, successes, failures)
        )


def _on_deferred_result(deferred, on_success, on_failure, on_no_result):
    """Handle the result of a synchronous ``Deferred``.

    If ``deferred`` has fire successfully, call ``on_success``.
    If ``deferred`` has failed, call ``on_failure``.
    If ``deferred`` has not yet fired, call ``on_no_result``.

    The value of ``deferred`` will be preserved, so that other callbacks and
    errbacks can be added to ``deferred``.

    :param Deferred[A] deferred: A synchronous Deferred.
    :param Callable[[Deferred[A], A], T] on_success: Called if the Deferred
        fires successfully.
    :param Callable[[Deferred[A], Failure], T] on_failure: Called if the
        Deferred fires unsuccessfully.
    :param Callable[[Deferred[A]], T] on_no_result: Called if the Deferred has
        not yet fired.

    :raises ImpossibleDeferredError: If the Deferred somehow
        triggers both a success and a failure.
    :raises TypeError: If the Deferred somehow triggers more than one success,
        or more than one failure.

    :return: Whatever is returned by the triggered callback.
    :rtype: ``T``
    """
    successes = []
    failures = []

    def capture(value, values):
        values.append(value)
        return value

    deferred.addCallbacks(
        partial(capture, values=successes),
        partial(capture, values=failures),
    )

    if successes and failures:
        raise ImpossibleDeferredError(deferred, successes, failures)
    elif failures:
        [failure] = failures
        return on_failure(deferred, failure)
    elif successes:
        [result] = successes
        return on_success(deferred, result)
    else:
        return on_no_result(deferred)


class _NoResult(object):
    """Matches a Deferred that has not yet fired."""

    @staticmethod
    def _got_result(deferred, result):
        return Mismatch(
            _u('No result expected on %r, found %r instead'
               % (deferred, result)))

    def match(self, deferred):
        """Match ``deferred`` if it hasn't fired."""
        return _on_deferred_result(
            deferred,
            on_success=self._got_result,
            on_failure=self._got_result,
            on_no_result=lambda _: None,
        )


# XXX: Maybe just a constant, rather than a function?
def no_result():
    """Match a Deferred that has not yet fired.

    For example, this will pass::

        assert_that(defer.Deferred(), no_result())

    But this will fail:

    >>> assert_that(defer.succeed(None), no_result())
    Traceback (most recent call last):
      ...
      File "testtools/assertions.py", line 22, in assert_that
        raise MismatchError(matchee, matcher, mismatch, verbose)
    testtools.matchers._impl.MismatchError: No result expected on <Deferred at ... current result: None>, found None instead

    As will this:

    >>> assert_that(defer.fail(RuntimeError('foo')), no_result())
    Traceback (most recent call last):
      ...
      File "testtools/assertions.py", line 22, in assert_that
        raise MismatchError(matchee, matcher, mismatch, verbose)
    testtools.matchers._impl.MismatchError: No result expected on <Deferred at ... current result: <twisted.python.failure.Failure <type 'exceptions.RuntimeError'>>>, found <twisted.python.failure.Failure <type 'exceptions.RuntimeError'>> instead
    """
    return _NoResult()


def _failure_content(failure):
    """Create a Content object for a Failure.

    :param Failure failure: The failure to create content for.
    :rtype: ``Content``
    """
    return TracebackContent(
        (failure.type, failure.value, failure.getTracebackObject()),
        None,
    )


class _Successful(object):
    """Matches a Deferred that has fired successfully."""

    def __init__(self, matcher):
        """Construct a ``_Successful`` matcher."""
        self._matcher = matcher

    @staticmethod
    def _got_failure(deferred, failure):
        deferred.addErrback(lambda _: None)
        return Mismatch(
            _u('Success result expected on %r, found failure result '
               'instead: %r' % (deferred, failure)),
            {'traceback': _failure_content(failure)},
        )

    @staticmethod
    def _got_no_result(deferred):
        return Mismatch(
            _u('Success result expected on {}, found no result '
               'instead'.format(deferred)))

    def match(self, deferred):
        """Match against the successful result of ``deferred``."""
        return _on_deferred_result(
            deferred,
            on_success=lambda _, value: self._matcher.match(value),
            on_failure=self._got_failure,
            on_no_result=self._got_no_result,
        )


# XXX: The Twisted name is successResultOf. Do we want to use that name?
def successful(matcher):
    """Match a Deferred that has fired successfully.

    For example::

        fires_with_the_answer = successful(Equals(42))
        deferred = defer.succeed(42)
        assert_that(deferred, fires_with_the_answer)

    This assertion will pass. However, if ``deferred`` had fired with a
    different value, or had failed, or had not fired at all, then it would
    fail.

    Use this instead of
    :py:meth:`twisted.trial.unittest.SynchronousTestCase.successResultOf`.

    :param matcher: A matcher to match against the result of a
        :class:`~twisted.internet.defer.Deferred`.
    :return: A matcher that can be applied to a synchronous
        :class:`~twisted.internet.defer.Deferred`.
    """
    return _Successful(matcher)


class _Failed(object):
    """Matches a Deferred that has failed."""

    def __init__(self, matcher):
        self._matcher = matcher

    def _got_failure(self, deferred, failure):
        # We have handled the failure, so suppress its output.
        deferred.addErrback(lambda _: None)
        return self._matcher.match(failure)

    @staticmethod
    def _got_success(deferred, success):
        return Mismatch(
            _u('Failure result expected on %r, found success '
               'result (%r) instead' % (deferred, success)), {})

    @staticmethod
    def _got_no_result(deferred):
        return Mismatch(
            _u('Failure result expected on %r, found no result instead'
               % (deferred,)))

    def match(self, deferred):
        return _on_deferred_result(
            deferred,
            on_success=self._got_success,
            on_failure=self._got_failure,
            on_no_result=self._got_no_result,
        )


# XXX: The Twisted name is failureResultOf. Do we want to use that name?
#
# XXX: failureResultOf also takes an *args of expected exception types. Do we
# want to provide that?
def failed(matcher):
    """Match a Deferred that has failed.

    For example::

        error = RuntimeError('foo')
        fails_at_runtime = failed(Equals(error))
        deferred = defer.fail(error)
        assert_that(deferred, fails_at_runtime)

    This assertion will pass. However, if ``deferred`` had fired successfully,
    had failed with a different error, or had not fired at all, then it would
    fail.

    Use this instead of
    :py:meth:`twisted.trial.unittest.SynchronousTestCase.failureResultOf`.

    :param matcher: A matcher to match against the result of a failing
        :class:`~twisted.internet.defer.Deferred`.
    :return: A matcher that can be applied to a synchronous
        :class:`~twisted.internet.defer.Deferred`.
    """
    return _Failed(matcher)

# TODO: helpers for adding matcher-based assertions in callbacks.

# TODO: Move the non-matcher stuff to _deferred.

# TODO: Fix configuration so that Twisted is included as dependency when we
# build on rtfd.
