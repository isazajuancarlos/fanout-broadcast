# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Juan Carlos Isaza

"""Tests de fanout-broadcast. Sin dependencias."""
import pytest

from fanout_broadcast import (
    Broadcaster, Outcome, Report, BroadcastError, env_enabled,
    DELIVERED, SKIPPED, FAILED,
)


# ---------------------------------------------------------------------------
# broadcast básico
# ---------------------------------------------------------------------------
def test_reparte_a_todos_los_habilitados():
    recibidos = {}
    bc = Broadcaster()
    bc.add("a", lambda m: recibidos.setdefault("a", m))
    bc.add("b", lambda m: recibidos.setdefault("b", m))
    report = bc.broadcast("hola")
    assert recibidos == {"a": "hola", "b": "hola"}
    assert report.ok
    assert len(report.delivered) == 2


def test_orden_de_entrega_es_el_de_registro():
    orden = []
    bc = Broadcaster()
    for n in ["x", "y", "z"]:
        bc.add(n, lambda m, n=n: orden.append(n))
    bc.broadcast("m")
    assert orden == ["x", "y", "z"]
    assert bc.names == ["x", "y", "z"]


def test_pasa_args_y_kwargs():
    got = {}
    bc = Broadcaster()
    bc.add("a", lambda *a, **k: got.update(args=a, kwargs=k))
    bc.broadcast(1, 2, urgente=True)
    assert got["args"] == (1, 2)
    assert got["kwargs"] == {"urgente": True}


# ---------------------------------------------------------------------------
# Aislamiento de fallos — el corazón de la librería
# ---------------------------------------------------------------------------
def test_un_canal_que_falla_no_detiene_a_los_demas():
    llamados = []
    bc = Broadcaster()
    bc.add("a", lambda m: llamados.append("a"))
    bc.add("boom", lambda m: (_ for _ in ()).throw(RuntimeError("caído")))
    bc.add("c", lambda m: llamados.append("c"))
    report = bc.broadcast("m")
    assert llamados == ["a", "c"]         # c se ejecutó pese al fallo de boom
    assert not report.ok
    assert len(report.failed) == 1
    assert report.get("boom").status == FAILED
    assert isinstance(report.get("boom").error, RuntimeError)


def test_report_expone_valor_devuelto():
    bc = Broadcaster()
    bc.add("a", lambda m: "resultado-a")
    report = bc.broadcast("m")
    assert report.get("a").value == "resultado-a"
    assert report.get("a").delivered


def test_raise_for_failures_lanza_tras_intentar_todos():
    llamados = []
    bc = Broadcaster()
    bc.add("a", lambda m: llamados.append("a"))
    bc.add("boom", lambda m: 1 / 0)
    bc.add("c", lambda m: llamados.append("c"))
    report = bc.broadcast("m")
    assert llamados == ["a", "c"]         # se intentaron todos ANTES de lanzar
    with pytest.raises(BroadcastError) as ei:
        report.raise_for_failures()
    assert "boom" in str(ei.value)
    assert len(ei.value.failures) == 1


def test_sin_fallos_raise_for_failures_no_hace_nada():
    bc = Broadcaster()
    bc.add("a", lambda m: None)
    bc.broadcast("m").raise_for_failures()   # no lanza


# ---------------------------------------------------------------------------
# Habilitar / deshabilitar
# ---------------------------------------------------------------------------
def test_canal_deshabilitado_se_omite():
    llamados = []
    bc = Broadcaster()
    bc.add("on", lambda m: llamados.append("on"))
    bc.add("off", lambda m: llamados.append("off"), enabled=False)
    report = bc.broadcast("m")
    assert llamados == ["on"]
    assert report.get("off").status == SKIPPED
    assert len(report.skipped) == 1


def test_enable_disable_en_runtime():
    llamados = []
    bc = Broadcaster()
    bc.add("a", lambda m: llamados.append("a"))
    bc.disable("a")
    bc.broadcast("m")
    assert llamados == []
    bc.enable("a")
    bc.broadcast("m")
    assert llamados == ["a"]


def test_is_enabled_y_keyerror():
    bc = Broadcaster()
    bc.add("a", lambda m: None, enabled=False)
    assert bc.is_enabled("a") is False
    with pytest.raises(KeyError):
        bc.is_enabled("inexistente")
    with pytest.raises(KeyError):
        bc.disable("inexistente")


def test_todo_deshabilitado_es_ok():
    bc = Broadcaster()
    bc.add("a", lambda m: None, enabled=False)
    report = bc.broadcast("m")
    assert report.ok            # nada falló
    assert bool(report) is True


# ---------------------------------------------------------------------------
# Registro: decorador, reemplazo, remove
# ---------------------------------------------------------------------------
def test_decorador_channel():
    bc = Broadcaster()
    marca = {}

    @bc.channel("discord")
    def a_discord(m):
        marca["discord"] = m

    bc.broadcast("hola")
    assert marca == {"discord": "hola"}


def test_nombre_repetido_reemplaza_conservando_posicion():
    bc = Broadcaster()
    bc.add("a", lambda m: "viejo")
    bc.add("b", lambda m: "b")
    bc.add("a", lambda m: "nuevo")       # reemplaza
    assert bc.names == ["a", "b"]        # posición conservada
    report = bc.broadcast("m")
    assert report.get("a").value == "nuevo"


def test_remove():
    bc = Broadcaster()
    bc.add("a", lambda m: None)
    bc.remove("a")
    assert bc.names == []
    bc.remove("inexistente")             # silencioso


def test_add_no_invocable_falla():
    bc = Broadcaster()
    with pytest.raises(TypeError):
        bc.add("a", "no soy funcion")


def test_add_es_encadenable():
    bc = Broadcaster()
    r = bc.add("a", lambda m: None).add("b", lambda m: None)
    assert r is bc
    assert bc.names == ["a", "b"]


# ---------------------------------------------------------------------------
# env_enabled
# ---------------------------------------------------------------------------
def test_env_enabled(monkeypatch):
    monkeypatch.setenv("DISCORD_ENABLED", "true")
    monkeypatch.setenv("EMAIL_ENABLED", "false")
    monkeypatch.setenv("SLACK_ENABLED", "ON")
    assert env_enabled("discord") is True
    assert env_enabled("email") is False
    assert env_enabled("slack") is True          # 'ON' cuenta
    assert env_enabled("ausente") is False       # default
    assert env_enabled("ausente", default=True) is True


# ---------------------------------------------------------------------------
# Outcome / Report helpers
# ---------------------------------------------------------------------------
def test_outcome_propiedades():
    o = Outcome("x", DELIVERED, "v", None)
    assert o.delivered and not o.failed and not o.skipped
    assert o.name == "x" and o.value == "v"


def test_report_repr_e_iteracion():
    bc = Broadcaster()
    bc.add("a", lambda m: None)
    bc.add("b", lambda m: 1 / 0)
    report = bc.broadcast("m")
    nombres = [o.name for o in report]
    assert nombres == ["a", "b"]
    assert "delivered=1" in repr(report) and "failed=1" in repr(report)
