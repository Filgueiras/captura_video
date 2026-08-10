# ADR-0021 — Julgar o áudio pelas amostras, não pela chegada de blocos

**Estado:** Aceito
**Data:** 2026-08-09

## Contexto

O selo de "sem áudio" e a pergunta antes de gravar existiam desde que a placa de
captura era a única fonte. Os dois liam o mesmo estado, e esse estado respondia à
pergunta **"chegou algum bloco de áudio?"** — um `threading.Event` acionado no
primeiro pacote com carimbo de tempo.

Com a placa isso funcionava por acidente. Uma entrada HDMI sem sinal costuma
falhar na abertura, e falha na abertura o teste pega. Quando a captura de tela
entrou ([0012](0012-ecra-por-ddagrab-janela-por-gdigrab.md)), a fonte natural de
som passou a ser a saída do próprio computador — e aí o acidente acabou:

**Uma fonte de loopback entrega blocos sem parar, mesmo com o PC em silêncio
absoluto.** Silêncio digital também é bloco. O teste diria "áudio ativo", a
pergunta antes de gravar não apareceria, e o arquivo sairia mudo — exatamente o
desastre que o selo foi escrito para evitar.

O mesmo furo existia na placa, só que mais escondido: HDMI conectado num aparelho
que não emite áudio abre normalmente e entrega silêncio.

Havia um segundo problema, este de disponibilidade do dado. O nível de áudio só
era calculado quando havia decodificação, e a decodificação só acontecia com a
monitoração ligada ou gravando em H.264:

```python
precisa_decodificar = self._monitorar or (gravador is not None and perfil == PERFIL_H264)
```

Na prévia com "Ouvir o áudio" desmarcado, ninguém olhava as amostras. Não havia
dado nenhum sobre o qual julgar.

## Decisão

Decodificar **sempre** o áudio e julgar pelo pico das amostras, em
[`captura.py`](../../capturador/captura.py):

| Constante | Valor | Papel |
|---|---|---|
| `LIMIAR_SINAL` | `0.002` (~-54 dBFS) | acima disto o bloco conta como som |
| `SEGUNDOS_SILENCIO` | `8.0` | silêncio seguido antes de acusar |

Nasce o estado `AUDIO_MUDO`, que se soma aos três que já existiam
(`DESLIGADO`, `ESPERANDO`, `FALHOU`, `ATIVO`). A carência de silêncio começa a
contar no **primeiro bloco**, não no início da captura: antes disso o estado
ainda é `ESPERANDO`, e cobrar sinal de uma entrada que nem começou seria falso
alarme.

O limiar não é zero de propósito. Silêncio digital é exatamente zero, mas
qualquer entrada analógica traz um chiado de fundo; um limiar em zero acusaria
"tem sinal" onde não há nada audível. Medido nesta máquina: um microfone mudo
entrega pico `0.0001`, ou seja, amplitude 3 em 32768.

O aviso antes de gravar distingue os dois casos, porque prometer a mesma coisa
nos dois seria mentira: entrada ausente é "o arquivo ficará mudo, e isso não tem
conserto"; entrada em silêncio é "a trilha existe e vai capturar o que vier a
tocar".

## Consequências

- O furo fecha para as duas famílias de fonte. Loopback mudo e placa sem áudio
  passam a acusar, e o custo é o mesmo código.
- A decodificação passou a ser incondicional. São blocos de 80 ms de PCM
  estéreo — irrisório perto do caminho do vídeo, e é o preço de ter o dado
  disponível o tempo todo em vez de só quando alguém está ouvindo. De quebra, o
  medidor de nível funciona na prévia sem monitoração, o que antes não
  acontecia.
- **Falso positivo é possível e foi aceito.** Gravar uma cena deliberadamente
  silenciosa por mais de 8 segundos acende o selo. Preferimos avisar demais a
  avisar de menos: o custo de um selo indevido é um segundo de atenção; o custo
  do silêncio é uma gravação perdida. A caixa *Avisar se faltar áudio* desliga a
  pergunta para quem se incomodar.
- Os 8 segundos são um palpite calibrado por pausa de fala, não uma medição.
  Curto demais dispara em conversa normal; longo demais deixa de servir.
- Medido nesta máquina, captura de ecrã com microfone mudo, sem monitoração e
  sem gravar: pico inicial de 0,42 no primeiro bloco, depois `0.0001`, e o
  estado virou `mudo` aos 8,0 s. Antes desta mudança o mesmo cenário reportava
  `ativo` indefinidamente e o nível ficava preso em zero.

## Alternativas consideradas

**Manter a contagem de blocos e confiar no medidor de nível da interface.** O
medidor está na tela e o usuário poderia olhar. Mas ele é um enfeite passivo:
não interrompe nada, não aparece no aviso antes de gravar e some quando o painel
está rolado. Quem esquece o áudio não está olhando o medidor.

**Limiar em zero absoluto.** Pegaria só o silêncio digital perfeito, que é o
caso do loopback com nada tocando. Não pegaria a placa com chiado de linha, que
é igualmente inútil e igualmente merece aviso.

**Janela de silêncio curta (2 s).** Detecta mais rápido, e acende em toda pausa
entre duas frases. O aviso perderia credibilidade na primeira meia hora de uso.

**Decodificar só uma amostragem dos blocos (um a cada dez).** Economizaria uma
decodificação que já é barata, e traria de volta o problema de ter o dado às
vezes. A economia não paga a condicional.
