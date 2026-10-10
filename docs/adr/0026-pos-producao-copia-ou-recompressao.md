# ADR-0026 — Pós-produção: uma operação só, com dois caminhos de saída

**Estado:** Aceito
**Data:** 2026-09-18

## Contexto

Capturar deixa duas tarefas pendentes que hoje empurram o usuário para outro
programa: **cortar as pontas** (a gravação sempre começa antes e termina depois
do que interessa) e **converter** (o perfil Original entrega ~150 MB/min, ótimo
para arquivar e grande demais para mandar a alguém). Somou-se a essas uma
terceira: **juntar** vários trechos num vídeo único.

A origem do pedido era importar essas funções de um projeto vizinho
(`matroska_subtitler`). Investigado, aquele projeto **não as tem**: ele é um
estúdio de legendas, e as suas quatro chamadas de FFmpeg usam `-c copy` — nada
lá recodifica, corta ou junta vídeo. Não havia código a trazer.

Em compensação, este projeto já tinha o essencial: FFmpeg embutido
([0002](0002-ffmpeg-embutido-via-pyav.md)), detecção de codificadores que abrem
de verdade ([0013](0013-so-codificadores-que-abrem.md)) e a convenção de tempo
em milissegundos ([0007](0007-base-de-tempo-em-milissegundos.md)).

## Decisão

**As três funções são a mesma função.** Converter é um trecho inteiro
recomprimido; cortar é um trecho com pontas; juntar são vários trechos em
sequência. [`edicao.py`](../../capturador/edicao.py) expõe uma
`montar(trechos, saída, receita)` e três atalhos com nome próprio. Uma
implementação, um tratamento de tempo, um de áudio, um de cancelamento.

**Dois caminhos de saída, e escolher entre eles é a decisão do usuário**, porque
não existe resposta universal:

| | Copiar | Recomprimir |
|---|---|---|
| Velocidade | instantâneo | minutos |
| Qualidade | idêntica ao original | perde uma geração |
| Corte | cai no **quadro-chave** anterior | **exato** |
| Tamanho | igual ao original | muito menor |
| Origens diferentes | recusa | uniformiza |

Medido nos arquivos de teste: uma gravação de 8 s da placa (MJPEG + PCM,
16,7 MB) virou 0,4 MB em H.264/AAC — 42× menor. E o corte por cópia caiu a
apenas 20 ms do pedido, porque MJPEG é todo quadro-chave; num H.264 com GOP de
2 s o desvio chegaria perto disso.

Quatro cuidados que o caminho ingênuo erra:

- **A cópia recarimba `pts` e `dts` juntos**, deslocados pela mesma quantidade.
  Mexer só no `pts` inverte a relação entre os dois e quebra a decodificação
  onde há quadros B.
- **A cópia começa no primeiro quadro-chave**, descartando o que o `seek`
  entregou antes dele; o desvio resultante vai para `Resultado.desvio_inicio` e
  a interface o informa em vez de fingir precisão que não houve.
- **O áudio recomprimido é numerado por contagem de amostras**, não por carimbo.
  Carimbo a carimbo, cada emenda entre trechos deixaria buraco ou sobreposição.
- **O `AudioResampler` do PyAV se amarra ao formato do primeiro quadro** e
  recusa um diferente depois. Juntando um MKV com PCM e um MP4 com AAC isso
  estoura na primeira emenda — descoberto medindo, não lendo. O reamostrador é
  refeito quando a assinatura da entrada muda, drenando o anterior para não
  perder as amostras que ele ainda segurava.

**Cancelar apaga a saída pela metade.** Um arquivo truncado com nome de vídeo
pronto é uma armadilha para quem for procurá-lo depois.

**A marcação é visual, e isso não é acabamento.** A primeira versão pedia os
pontos de corte em segundos digitados, e estava errada: para marcar onde o
assunto começa é preciso *ver* onde ele começa, senão o trabalho vira adivinhar,
conferir noutro programa e voltar para corrigir — exatamente o que a ferramenta
deveria poupar. A prévia ocupa a janela, a barra percorre o arquivo, `I` e `O`
fixam o quadro que está na tela, e uma faixa mostra o que sobra.

O que torna isso viável é o custo de um salto: medido neste material,
**~11 ms** para posicionar e decodificar um quadro 1080p, porque MJPEG é todo
quadro-chave. Num H.264 com GOP longo é mais caro, e por isso o quadro é pedido
40 ms depois do último movimento da barra, e não a cada pixel arrastado.

**Janela própria**, e não um cartão no painel: é o que se faz *depois*, com a
captura parada, e misturar obrigaria a interface de captura a carregar controles
inúteis durante a gravação. O trabalho roda em `QThread`
([0014](0014-trabalho-demorado-em-qthread.md)).

**A porta de entrada fica no cabeçalho**, ao lado do nome do programa. A
primeira tentativa a pôs no fim do cartão *Gravação*, e isso a tornou
inalcançável: medido, o botão caía em `y=1007` numa janela de 800 px de altura,
dentro da área rolável — existia sem ser encontrável. O painel lateral rola e é
feito de ajustes da captura; abrir outra ferramenta não é um ajuste, e o
cabeçalho é a única faixa que não se move
([0016](0016-aparencia-centralizada-e-paineis-por-lista.md)).

## Consequências

- O ciclo captura → ajuste → entrega fecha dentro do programa.
- **A sincronia sobrevive.** Medido numa saída que juntou dois clipes, cortou um
  deles e recomprimiu tudo: **+1,7 ms** de desencontro. Juntar por cópia saiu em
  −2,6 ms, melhor que os −7,7 ms do próprio material de origem.
- `opcoes_codificador` passou a ser compartilhada com a captura, com um
  parâmetro `ao_vivo`: gravando, `veryfast`/`zerolatency`, porque perder quadro
  é pior que arquivo maior; convertendo, `medium`, porque não há quadro a perder
  — só tempo.
- **Juntar por cópia recusa origens diferentes**, com a mensagem dizendo quais
  arquivos divergem e oferecendo recomprimir. Entregar um arquivo que a maioria
  dos reprodutores mostra quebrado a partir da emenda seria pior.
- O programa cresceu para além de capturar. É uma ampliação real de escopo, e a
  fronteira que a mantém honesta é `edicao.py` não saber nada de captura: ele
  recebe caminhos de arquivo, não dispositivos.
- A prévia é **silenciosa** e a marcação é por quadro, não por forma de onda.
  Para tirar as pontas e emendar gravações é o suficiente; para cortar em cima
  de uma sílaba, não é — e esse é o limite assumido desta versão.
- `TelaVideo` passou a ser compartilhada com a janela de captura. Uma classe a
  menos para manter, e a prévia da pós-produção herda de graça a proporção
  correta e as barras nas sobras.

## Alternativas consideradas

**Chamar o `ffmpeg` de linha de comando.** Menos código, e o `concat` do FFmpeg
já resolveria a junção. Rejeitado porque no Linux o binário externo não é
sequer pré-requisito ([COMO_RODAR](../COMO_RODAR.md)), e porque progresso e
cancelamento viriam de raspar texto de stderr em vez de um laço nosso.

**Só recomprimir, sem o caminho de cópia.** Um caminho de código, tudo exato.
Rejeitado pelo número: cortar as pontas de uma gravação longa é instantâneo por
cópia e leva minutos recomprimindo, e ainda perde uma geração de qualidade sem
que o usuário tenha pedido.

**Cortar sempre exato recomprimindo só o primeiro GOP** (o que ferramentas de
corte "sem perda" fazem: recodificam o pedaço inicial e copiam o resto).
Resolveria a única desvantagem da cópia. É mais código do que os três recursos
inteiros somados, e ficou para quando o desvio incomodar de verdade — o campo
`desvio_inicio` existe justamente para medir isso.

**Pedir os tempos digitados, sem prévia.** Foi a primeira versão, e durou uma
rodada de uso. É muito menos código e é inutilizável: ninguém sabe de cor em que
segundo a gravação parou de mostrar a área de trabalho.

**Linha do tempo com forma de onda e várias faixas.** É o que um editor de
verdade tem. Fora de escopo para "ajustar o que acabei de capturar"; a prévia
com marcação por quadro cobre o caso real sem trazer um editor inteiro junto.
