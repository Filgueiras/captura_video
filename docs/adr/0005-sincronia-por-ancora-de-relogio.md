# ADR-0005 — Sincronia por âncora de relógio comum

**Estado:** Aceito
**Data:** 2026-07-26

## Contexto

Vindo de dois containers independentes ([0004](0004-video-e-audio-em-containers-separados.md)),
vídeo e áudio chegam com carimbos de tempo (*timestamps*) que **não são
comparáveis entre si**: cada demuxer começa a contar do seu próprio zero, no
instante em que foi aberto. Como as duas threads não abrem no mesmo milissegundo,
gravar os carimbos crus produz um arquivo com áudio adiantado ou atrasado por
uma quantidade arbitrária — tipicamente centenas de milissegundos, o suficiente
para o descompasso ser visível numa boca falando.

A tentação óbvia é carimbar cada pacote com o relógio do sistema no momento em
que ele é lido. Isso alinha o começo, mas destrói o intervalo entre quadros: o
momento em que a thread *acorda* para processar um pacote sofre jitter do
escalonador (facilmente 5–15 ms), enquanto a placa entrega os quadros com
espaçamento praticamente perfeito. O resultado é um arquivo com taxa de quadros
trêmula, que alguns players exibem com micro-engasgos.

## Decisão

Uma **âncora de relógio comum**, tomada uma vez, no instante em que a gravação
começa. A classe `_Ancora` em [`captura.py`](../../capturador/captura.py):

```
t0 = time.monotonic()          # um só, compartilhado pelos dois fluxos
ancora_video = _Ancora(t0)
ancora_audio = _Ancora(t0)
```

No **primeiro** pacote de cada fluxo, a âncora registra dois valores: o carimbo
que o dispositivo trazia e quanto tempo de relógio havia passado desde `t0`. Dali
em diante, todo pacote é convertido por subtração:

```
tempo_no_arquivo = (carimbo_do_dispositivo - base) + deslocamento
```

Ou seja: **o relógio do sistema decide onde cada fluxo começa; o relógio da placa
decide o espaçamento dentro de cada fluxo.**

## Consequências

- Os dois fluxos começam alinhados porque compartilham o mesmo `t0`, mesmo tendo
  sido abertos com segundos de diferença.
- Os intervalos suaves gerados pelo hardware são preservados intactos — nenhum
  jitter de escalonador entra no arquivo.
- Medido nesta máquina: **~2 ms de deriva por hora** entre as trilhas. Abaixo do
  limiar de percepção (~45 ms para lábios e som), com folga de mais de uma ordem
  de grandeza.
- Se o relógio da placa derivar de verdade em relação ao do sistema, essa deriva
  **não** é corrigida: a âncora é fixada uma vez e nunca reajustada. É uma
  escolha consciente — corrigir exigiria inserir ou remover amostras de áudio, o
  que produz estalos audíveis, e a deriva medida não justifica isso.
- Um pacote sem carimbo nenhum cai para o relógio de parede (`agora`), que é o
  melhor palpite disponível.
- O `resumir_gravacao()` mede a sincronia do arquivo pelo **fim do conteúdo** de
  cada trilha, e não pelo carimbo do último pacote. Um pacote de áudio dura ~80 ms
  e um quadro ~33 ms; comparar os *inícios* dos últimos pacotes acrescentaria
  dezenas de milissegundos de puro erro de arredondamento a um número que existe
  para detectar erros de dezenas de milissegundos.

## Alternativas consideradas

**Carimbar tudo com o relógio de parede na leitura.** Alinha o início e estraga
o espaçamento, como descrito acima.

**Usar os carimbos crus de cada dispositivo.** Preserva o espaçamento e erra o
alinhamento por uma quantidade arbitrária. É o que acontece quando não se faz
nada — e é o bug que originou esta decisão.

**Ressincronizar periodicamente ao longo da gravação.** Corrigiria deriva de
relógio, ao custo de descontinuidades audíveis. Com 2 ms/hora medidos, seria
resolver um problema que não existe criando um que existe.
