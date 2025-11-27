from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any

from OpenSSL import SSL
from twisted.internet._sslverify import _setAcceptableProtocols
from twisted.internet.ssl import (
    AcceptableCiphers,
    CertificateOptions,
    optionsForClientTLS,
    platformTrust,
)
from twisted.web.client import BrowserLikePolicyForHTTPS
from twisted.web.iweb import IPolicyForHTTPS
from zope.interface.declarations import implementer
from zope.interface.verify import verifyObject

from scrapy.core.downloader.tls import (
    DEFAULT_CIPHERS,
    ScrapyClientTLSOptions,
    openssl_methods,
)
from scrapy.exceptions import ScrapyDeprecationWarning
from scrapy.utils.deprecate import method_is_overridden
from scrapy.utils.misc import build_from_crawler, load_object

if TYPE_CHECKING:
    from twisted.internet._sslverify import ClientTLSOptions

    # typing.Self requires Python 3.11
    from typing_extensions import Self

    from scrapy.crawler import Crawler
    from scrapy.settings import BaseSettings


@implementer(IPolicyForHTTPS)
class ScrapyClientContextFactory(BrowserLikePolicyForHTTPS):
    """
    Non-peer-certificate verifying HTTPS context factory

    Default OpenSSL method is TLS_METHOD (also called SSLv23_METHOD)
    which allows TLS protocol negotiation

    'A TLS/SSL connection established with [this method] may
     understand the TLSv1, TLSv1.1 and TLSv1.2 protocols.'
    """

    def __init__(
        self,
        method: int | None = None,
        tls_verbose_logging: bool = False,
        tls_ciphers: str | None = None,
        *args: Any,
        **kwargs: Any,
    ):
        super().__init__(*args, **kwargs)
        # Prefer a modern TLS method when available. Fall back to older
        # SSLv23_METHOD for compatibility if TLS_METHOD is not present in
        # the local pyOpenSSL/OpenSSL bindings.
        if method is None:
            self._ssl_method: int = getattr(SSL, "TLS_METHOD", getattr(SSL, "SSLv23_METHOD"))
        else:
            self._ssl_method: int = method
        self.tls_verbose_logging: bool = tls_verbose_logging
        self.tls_ciphers: AcceptableCiphers
        if tls_ciphers:
            self.tls_ciphers = AcceptableCiphers.fromOpenSSLCipherString(tls_ciphers)
        else:
            self.tls_ciphers = DEFAULT_CIPHERS
        if method_is_overridden(type(self), ScrapyClientContextFactory, "getContext"):
            warnings.warn(
                "Overriding ScrapyClientContextFactory.getContext() is deprecated and that method"
                " will be removed in a future Scrapy version. Override creatorForNetloc() instead.",
                category=ScrapyDeprecationWarning,
                stacklevel=2,
            )

    @classmethod
    def from_crawler(
        cls,
        crawler: Crawler,
        method: int = SSL.SSLv23_METHOD,
        *args: Any,
        **kwargs: Any,
    ) -> Self:
        tls_verbose_logging: bool = crawler.settings.getbool(
            "DOWNLOADER_CLIENT_TLS_VERBOSE_LOGGING"
        )
        tls_ciphers: str | None = crawler.settings["DOWNLOADER_CLIENT_TLS_CIPHERS"]
        return cls(  # type: ignore[misc]
            method=method,
            tls_verbose_logging=tls_verbose_logging,
            tls_ciphers=tls_ciphers,
            *args,
            **kwargs,
        )

    def getCertificateOptions(self) -> CertificateOptions:
        # setting verify=True will require you to provide CAs
        # to verify against; in other words: it's not that simple
        return CertificateOptions(
            verify=False,
            method=self._ssl_method,
            fixBrokenPeers=True,
            acceptableCiphers=self.tls_ciphers,
        )

    # kept for old-style HTTP/1.0 downloader context twisted calls,
    # e.g. connectSSL()
    def getContext(self, hostname: Any = None, port: Any = None) -> SSL.Context:
        ctx: SSL.Context = self.getCertificateOptions().getContext()
        # Ensure we disable known weak/obsolete protocol versions when the
        # OpenSSL options are available. Fall back gracefully when a flag
        # isn't defined in the local OpenSSL build.
        op_no_tlsv1 = getattr(SSL, "OP_NO_TLSv1", 0)
        op_no_tlsv1_1 = getattr(SSL, "OP_NO_TLSv1_1", 0)
        op_no_sslv2 = getattr(SSL, "OP_NO_SSLv2", 0)
        op_no_sslv3 = getattr(SSL, "OP_NO_SSLv3", 0)
        # Keep legacy server connect flag if present, but still OR with the
        # 'no' flags to avoid negotiating old protocols by default.
        op_legacy = getattr(SSL, "OP_LEGACY_SERVER_CONNECT", 0x4)
        disable_flags = op_no_tlsv1 | op_no_tlsv1_1 | op_no_sslv2 | op_no_sslv3
        ctx.set_options(op_legacy | disable_flags)
        return ctx

    def creatorForNetloc(self, hostname: bytes, port: int) -> ClientTLSOptions:
        return ScrapyClientTLSOptions(
            hostname.decode("ascii"),
            self.getContext(),
            verbose_logging=self.tls_verbose_logging,
        )


@implementer(IPolicyForHTTPS)
class BrowserLikeContextFactory(ScrapyClientContextFactory):
    """
    Twisted-recommended context factory for web clients.

    Quoting the documentation of the :class:`~twisted.web.client.Agent` class:

        The default is to use a
        :class:`~twisted.web.client.BrowserLikePolicyForHTTPS`, so unless you
        have special requirements you can leave this as-is.

    :meth:`creatorForNetloc` is the same as
    :class:`~twisted.web.client.BrowserLikePolicyForHTTPS` except this context
    factory allows setting the TLS/SSL method to use.

    The default OpenSSL method is ``TLS_METHOD`` (also called
    ``SSLv23_METHOD``) which allows TLS protocol negotiation.
    """

    def creatorForNetloc(self, hostname: bytes, port: int) -> ClientTLSOptions:
        # trustRoot set to platformTrust() will use the platform's root CAs.
        #
        # This means that a website like https://www.cacert.org will be rejected
        # by default, since CAcert.org CA certificate is seldom shipped.
        return optionsForClientTLS(
            hostname=hostname.decode("ascii"),
            trustRoot=platformTrust(),
            extraCertificateOptions={"method": self._ssl_method},
        )


@implementer(IPolicyForHTTPS)
class AcceptableProtocolsContextFactory:
    """Context factory to used to override the acceptable protocols
    to set up the [OpenSSL.SSL.Context] for doing NPN and/or ALPN
    negotiation.
    """

    def __init__(self, context_factory: Any, acceptable_protocols: list[bytes]):
        verifyObject(IPolicyForHTTPS, context_factory)
        self._wrapped_context_factory: Any = context_factory
        self._acceptable_protocols: list[bytes] = acceptable_protocols

    def creatorForNetloc(self, hostname: bytes, port: int) -> ClientTLSOptions:
        options: ClientTLSOptions = self._wrapped_context_factory.creatorForNetloc(
            hostname, port
        )
        _setAcceptableProtocols(options._ctx, self._acceptable_protocols)
        return options


def load_context_factory_from_settings(
    settings: BaseSettings, crawler: Crawler
) -> IPolicyForHTTPS:
    ssl_method = openssl_methods[settings.get("DOWNLOADER_CLIENT_TLS_METHOD")]
    context_factory_cls = load_object(settings["DOWNLOADER_CLIENTCONTEXTFACTORY"])
    # try method-aware context factory
    try:
        context_factory = build_from_crawler(
            context_factory_cls,
            crawler,
            method=ssl_method,
        )
    except TypeError:
        # use context factory defaults
        context_factory = build_from_crawler(
            context_factory_cls,
            crawler,
        )
        msg = (
            f"{settings['DOWNLOADER_CLIENTCONTEXTFACTORY']} does not accept "
            "a `method` argument (type OpenSSL.SSL method, e.g. "
            "OpenSSL.SSL.SSLv23_METHOD) and/or a `tls_verbose_logging` "
            "argument and/or a `tls_ciphers` argument. Please, upgrade your "
            "context factory class to handle them or ignore them."
        )
        warnings.warn(msg)

    return context_factory
