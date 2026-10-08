# Conceptos cripto y tech (para explicar en forma educativa, nunca como consejo de inversión)

- ATH (all-time high): precio máximo histórico. "Distancia al ATH": cuánto está por debajo. Ejemplo: si el ATH fue 100 y hoy vale 60, está 40% abajo y necesita subir 66,7% para volver.
- ATH ajustado por supply: si desde el ATH se emitieron muchos tokens, volver al mismo precio exige un market cap mayor. ATH Intelligence calcula el "ATH honesto" como market cap del máximo ÷ supply de hoy.
- Fear & Greed Index: índice de 0 a 100 del sentimiento del mercado cripto (bajo = miedo, alto = codicia). Es contexto, no señal de compra o venta. El bot demo usa el de alternative.me.
- Token unlock: liberación programada de tokens bloqueados (equipo, inversores, ecosistema) según un calendario de vesting con cliff y liberaciones periódicas. Aumenta la oferta circulante y a veces genera presión de venta, pero no es una predicción. Conviene verificar en fuentes primarias.
- Ballena (whale): wallet o trader que mueve montos muy grandes.
- Spot vs futuros perpetuos: spot es comprar el activo real; los perpetuos permiten apalancamiento y posiciones en corto, con riesgo de liquidación y costos de funding. El apalancamiento multiplica ganancias y pérdidas.
- Honeypot: token que se puede comprar pero no vender. Rug pull: los creadores retiran la liquidez o venden todo de golpe. Señales a revisar: contrato verificado, permisos del owner (mint ilimitado, blacklist, pausar transferencias, impuestos modificables), liquidez bloqueada o quemada, concentración de holders, probar una venta chica, promesas de ganancias garantizadas. Ninguna herramienta es 100% segura.
- Seguridad de wallets: seed phrase offline (nunca en fotos, mails ni nube), hardware wallet para montos grandes, wallet separada para probar dApps, no firmar lo que no entendés, revisar y revocar aprobaciones viejas, verificar URLs, 2FA con app.
- Launchpool: programa de un exchange (por ejemplo Binance Launchpool) donde se bloquean tokens para recibir tokens nuevos. Yield farming: aportar liquidez o depositar en protocolos DeFi (por ejemplo vaults como Beefy) para obtener rendimiento, con riesgos de smart contract y de mercado.
- DeFi: finanzas descentralizadas sobre blockchains (préstamos como Aave o Compound, exchanges descentralizados como Uniswap, stablecoins como las de MakerDAO).
- Programa de referidos de exchange: links que atribuyen usuarios nuevos a un partner; algunos exchanges ofrecen APIs para verificar el UID del referido.
- RAG (retrieval-augmented generation): el modelo de IA responde usando documentos del cliente como contexto, para no inventar.
- Ruteo de modelos: mandar cada consulta al modelo de IA más adecuado según tarea y costo (modelo barato para preguntas simples, uno más potente para casos complejos).
- API REST con API key: interfaz web para que otros sistemas consulten datos, autenticada con una clave (por ejemplo, el header x-api-key en ATH Intelligence).
- Webhook: aviso automático que un sistema envía a otro cuando pasa un evento.
