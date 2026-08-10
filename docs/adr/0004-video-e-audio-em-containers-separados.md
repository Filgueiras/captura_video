# ADR-0004 — Vídeo e áudio como containers independentes, uma thread cada

**Estado:** Aceito
**Data:** 2026-07-26

## Contexto

Uma placa HDMI→USB expõe duas funções USB distintas: uma de vídeo (UVC) e uma de
áudio (UAC). Elas aparecem no sistema como dois dispositivos separados, ainda
que sejam o mesmo pedaço de plástico.

No Windows, o `dshow` até aceita abrir vídeo e áudio numa entrada só
(`-f dshow -i video=X:audio=Y`). No Linux essa opção **não existe**: `v4l2` e
`pulse`/`alsa` são demuxers diferentes e ponto final.

## Decisão

Sempre **dois containers**, abertos por `av.open()` separadamente, cada um lido
por sua própria thread (`_laco_video` e `_laco_audio` em
[`captura.py`](../../capturador/captura.py)). Igual nos dois sistemas.

## Consequências

- Um caminho de código só para as duas plataformas — o oposto de otimizar o
  Windows e depois descobrir que o Linux precisa de outra coisa inteira.
- Se o áudio falhar ao abrir, o vídeo continua. O usuário recebe um aviso
  ("Áudio indisponível, seguindo só com vídeo") em vez de uma sessão morta. Com
  entrada combinada, um erro em qualquer metade derruba tudo.
- As duas threads são de leitura bloqueante pura, o que faz o GIL do Python ser
  irrelevante aqui: `demux()` solta o GIL enquanto espera o dispositivo.
- **A sincronia passa a ser problema nosso.** Dois containers têm dois relógios
  sem relação entre si. É exatamente isso que o
  [0005](0005-sincronia-por-ancora-de-relogio.md) resolve.
- Dois escritores concorrendo pelo mesmo arquivo de saída: o `Gravador` protege
  o `mux` com um `threading.Lock`, porque o container do FFmpeg não é seguro
  para escrita simultânea.
- A gravação só pode começar depois que **os dois** fluxos entregarem o primeiro
  pacote — é preciso o cabeçalho de cada um para montar o arquivo de saída. Daí
  os `threading.Event` (`_pronto_video`, `_pronto_audio`) e a espera com prazo
  em `iniciar_gravacao()`: 5 s para o vídeo (sem ele não há gravação) e 2 s para
  o áudio (sem ele, grava-se só o vídeo).

## Alternativas consideradas

**Entrada combinada do `dshow` no Windows e separada no Linux.** Melhoraria a
sincronia no Windows de graça, ao custo de dois motores de captura para manter e
testar. Rejeitado: a âncora de relógio do [0005](0005-sincronia-por-ancora-de-relogio.md)
mede ~2 ms de deriva por hora, o que torna o ganho teórico irrelevante.

**Uma thread só, alternando entre os dois containers.** `demux()` bloqueia; ficar
alternando exigiria leitura não-bloqueante e um laço de espera ativa, gastando
CPU para piorar a latência dos dois lados.

**Threads da própria Qt (`QThread`) em vez de `threading.Thread`.** `QThread` é
usado onde o resultado volta para a interface por sinal
([0014](0014-trabalho-demorado-em-qthread.md)). Aqui não volta nada por sinal —
o quadro é depositado num atributo protegido por lock e a interface o busca
quando quiser ([0015](0015-previa-por-polling.md)) —, então a thread padrão do
Python basta e mantém o motor de captura independente do Qt.
