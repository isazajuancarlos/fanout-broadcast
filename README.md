# fanout-broadcast

Reparte un mensaje a varios canales, **aísla los fallos** y te dice qué pasó en
cada uno. Python puro, sin dependencias.

## El problema

Quieres mandar lo mismo a varios sitios —Slack, Discord, un webhook, un email,
una página de LinkedIn— y dos cosas te importan:

1. Que **un canal caído no tumbe a los demás**. Si Discord está fallando, el
   email debe salir igual.
2. **Enterarte** de qué se entregó y qué no, sin bucear en los logs.

El patrón ingenuo —un `for` que llama a cada canal— falla en lo primero: la
primera excepción corta el reparto. Y suele fallar en lo segundo: cada canal se
traga su error en un `try/except` disperso.

## La solución

```python
from fanout_broadcast import Broadcaster

bc = Broadcaster()
bc.add("discord",  publicar_discord)
bc.add("telegram", publicar_telegram)
bc.add("email",    publicar_email, enabled=False)   # apagado por ahora

report = bc.broadcast("¡Nueva versión publicada!")

if not report.ok:
    for o in report.failed:
        log.error("%s falló: %s", o.name, o.error)
```

Cada canal es un simple invocable. `broadcast` los llama a todos —en orden de
registro— con los argumentos que le pases, **captura la excepción de cada uno por
separado**, y devuelve un `Report`. Un canal que lanza queda como `failed` y los
siguientes se ejecutan igual.

## Instalación

```bash
pip install fanout-broadcast
```

Sin dependencias. Requiere Python ≥ 3.9.

## El reporte

```python
report.ok           # True si ningún canal falló
report.delivered    # [Outcome, ...] los que entregaron
report.failed       # [Outcome, ...] los que lanzaron (con .error)
report.skipped      # [Outcome, ...] los deshabilitados
report.get("discord")   # el Outcome de un canal concreto

for o in report:                    # iterable, en orden
    print(o.name, o.status)         # "delivered" / "skipped" / "failed"
```

¿Prefieres escalar tras intentarlo todo? `report.raise_for_failures()` lanza una
`BroadcastError` **después** de haber llamado a todos los canales — al revés que
dejar que la primera excepción corte el reparto.

## Encender y apagar canales

```python
bc.disable("discord")        # en runtime
bc.enable("discord")
bc.is_enabled("email")
```

Y para el patrón habitual de conmutar por variable de entorno:

```python
from fanout_broadcast import env_enabled

bc.add("discord", publicar_discord, enabled=env_enabled("discord"))
# mira DISCORD_ENABLED en el entorno
```

## También como decorador

```python
@bc.channel("discord")
def a_discord(msg):
    requests.post(WEBHOOK, json={"content": msg})
```

## De dónde viene

Salió de un agente de publicación multicanal. Extraje solo la fontanería: el
*qué* se publica y a *quién* es la lógica de tu aplicación; el *cómo* repartir con
aislamiento de fallos y reporte es genérico, y servía para notificaciones,
alertas o webhooks tanto como para redes sociales. Por eso es una librería.

## Tests

```bash
pip install "fanout-broadcast[test]"
pytest
```

19 tests centrados en el aislamiento de fallos, el orden, los toggles y el
reporte. Verificados por mutación (estrechar el `except` que aísla rompe justo
los tests del aislamiento).

## Licencia

Apache-2.0.
