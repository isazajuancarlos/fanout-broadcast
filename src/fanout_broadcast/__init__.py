# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Juan Carlos Isaza

"""fanout-broadcast — reparte un mensaje a varios canales, aísla los fallos y te
dice qué pasó en cada uno.

El problema: quieres mandar la misma cosa a varios sitios —Slack, Discord, un
webhook, un email, una página de LinkedIn— y no quieres que un canal caído tumbe
a los demás, ni enterarte del fallo por un log perdido.

    from fanout_broadcast import Broadcaster

    bc = Broadcaster()
    bc.add("discord",  publicar_discord)
    bc.add("telegram", publicar_telegram)
    bc.add("email",    publicar_email, enabled=False)   # apagado por ahora

    report = bc.broadcast("¡Nueva versión publicada!")

    if not report.ok:
        for o in report.failed:
            log.error("%s falló: %s", o.name, o.error)

Cada canal es un simple invocable. Si uno lanza una excepción, se captura, se
registra en el reporte como ``failed`` y **los demás siguen**. Los apagados
salen como ``skipped``. Nunca se pierde en silencio ni detiene al resto.

Nació de un agente de publicación multicanal, extrayendo solo la fontanería: el
qué se publica y a quién es tuyo; el cómo repartir con aislamiento es esto. Sin
dependencias.
"""
from __future__ import annotations

import os
from collections import namedtuple

__all__ = [
    "Broadcaster",
    "Outcome",
    "Report",
    "BroadcastError",
    "env_enabled",
    "DELIVERED",
    "SKIPPED",
    "FAILED",
    "__version__",
]

__version__ = "0.1.1"

DELIVERED = "delivered"   # el canal se ejecutó sin lanzar
SKIPPED = "skipped"       # el canal estaba deshabilitado
FAILED = "failed"         # el canal lanzó una excepción (capturada)


class Outcome(namedtuple("Outcome", ["name", "status", "value", "error"])):
    """Resultado de un canal en un broadcast.

    - ``name``   nombre del canal.
    - ``status`` uno de :data:`DELIVERED`, :data:`SKIPPED`, :data:`FAILED`.
    - ``value``  lo que devolvió el canal (si entregó), si no ``None``.
    - ``error``  la excepción capturada (si falló), si no ``None``.
    """
    __slots__ = ()

    @property
    def delivered(self) -> bool:
        return self.status == DELIVERED

    @property
    def failed(self) -> bool:
        return self.status == FAILED

    @property
    def skipped(self) -> bool:
        return self.status == SKIPPED


class Report:
    """Lo que pasó en un :meth:`Broadcaster.broadcast`. Iterable sobre los
    :class:`Outcome` en el orden de los canales."""

    __slots__ = ("outcomes",)

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)

    def __iter__(self):
        return iter(self.outcomes)

    def __len__(self):
        return len(self.outcomes)

    def __bool__(self):
        """``True`` si no hubo fallos (ver :attr:`ok`)."""
        return self.ok

    @property
    def delivered(self):
        """Los canales que entregaron."""
        return [o for o in self.outcomes if o.status == DELIVERED]

    @property
    def failed(self):
        """Los canales que lanzaron una excepción."""
        return [o for o in self.outcomes if o.status == FAILED]

    @property
    def skipped(self):
        """Los canales que estaban deshabilitados."""
        return [o for o in self.outcomes if o.status == SKIPPED]

    @property
    def ok(self) -> bool:
        """``True`` si ningún canal falló. Un broadcast donde todo estaba
        deshabilitado también es ``ok`` (nada falló)."""
        return not any(o.status == FAILED for o in self.outcomes)

    def get(self, name):
        """El :class:`Outcome` del canal ``name``, o ``None``."""
        for o in self.outcomes:
            if o.name == name:
                return o
        return None

    def raise_for_failures(self):
        """Lanza :class:`BroadcastError` si algún canal falló. Útil para
        escalar tras haber intentado TODOS los canales (a diferencia de dejar
        que la primera excepción corte el reparto)."""
        fallos = self.failed
        if fallos:
            raise BroadcastError(fallos)

    def __repr__(self):
        return (f"Report(delivered={len(self.delivered)}, "
                f"failed={len(self.failed)}, skipped={len(self.skipped)})")


class BroadcastError(Exception):
    """Se lanza desde :meth:`Report.raise_for_failures` cuando hubo fallos.
    ``.failures`` lista los :class:`Outcome` fallidos."""

    def __init__(self, failures):
        self.failures = list(failures)
        nombres = ", ".join(o.name for o in self.failures)
        super().__init__(f"{len(self.failures)} canal(es) fallaron: {nombres}")


class Broadcaster:
    """Reparte cada mensaje a los canales registrados, con aislamiento de fallos.

    Registra canales con :meth:`add` (o el decorador :meth:`channel`); cada uno
    es un invocable. :meth:`broadcast` los llama a todos con los argumentos que
    le pases, captura las excepciones de cada uno por separado, y devuelve un
    :class:`Report`. El orden de entrega es el de registro.
    """

    def __init__(self):
        self._channels = []   # lista de [name, fn, enabled] preservando orden

    def _find(self, name):
        for entry in self._channels:
            if entry[0] == name:
                return entry
        return None

    def add(self, name, fn, enabled=True):
        """Registra un canal. ``fn`` se invocará con los argumentos de
        :meth:`broadcast`. Devuelve ``self`` (encadenable). Un nombre repetido
        reemplaza al canal anterior conservando su posición."""
        if not callable(fn):
            raise TypeError(f"el canal {name!r} debe ser invocable")
        entry = self._find(name)
        if entry is not None:
            entry[1] = fn
            entry[2] = bool(enabled)
        else:
            self._channels.append([name, fn, bool(enabled)])
        return self

    def channel(self, name, enabled=True):
        """Registra un canal como decorador::

            @bc.channel("discord")
            def a_discord(msg): ...
        """
        def deco(fn):
            self.add(name, fn, enabled=enabled)
            return fn
        return deco

    def remove(self, name):
        """Elimina un canal. Devuelve ``self``. Silencioso si no existe."""
        self._channels = [e for e in self._channels if e[0] != name]
        return self

    def enable(self, name):
        """Habilita un canal. Devuelve ``self``."""
        return self.set_enabled(name, True)

    def disable(self, name):
        """Deshabilita un canal. Devuelve ``self``."""
        return self.set_enabled(name, False)

    def set_enabled(self, name, value):
        entry = self._find(name)
        if entry is None:
            raise KeyError(name)
        entry[2] = bool(value)
        return self

    def is_enabled(self, name) -> bool:
        entry = self._find(name)
        if entry is None:
            raise KeyError(name)
        return entry[2]

    @property
    def names(self):
        """Los nombres de los canales, en orden de registro."""
        return [e[0] for e in self._channels]

    def broadcast(self, *args, **kwargs) -> Report:
        """Llama a cada canal habilitado con ``(*args, **kwargs)``. Aísla las
        excepciones: un canal que lanza no impide a los siguientes. Devuelve un
        :class:`Report` con un :class:`Outcome` por canal."""
        outcomes = []
        for name, fn, enabled in self._channels:
            if not enabled:
                outcomes.append(Outcome(name, SKIPPED, None, None))
                continue
            try:
                value = fn(*args, **kwargs)
                outcomes.append(Outcome(name, DELIVERED, value, None))
            except Exception as e:  # noqa: BLE001 — aislar es el objetivo
                outcomes.append(Outcome(name, FAILED, None, e))
        return Report(outcomes)


def env_enabled(name, default=False, suffix="_ENABLED"):
    """Ayuda para el patrón común de conmutar canales por entorno: lee
    ``{NAME}{suffix}`` (en mayúsculas) y lo interpreta como booleano
    (``"true"``/``"1"``/``"yes"``/``"on"``, sin distinguir mayúsculas).

        bc.add("discord", a_discord, enabled=env_enabled("discord"))
        # -> mira la variable DISCORD_ENABLED
    """
    raw = os.getenv(f"{name.upper()}{suffix}")
    if raw is None:
        return bool(default)
    return raw.strip().lower() in ("true", "1", "yes", "on")
