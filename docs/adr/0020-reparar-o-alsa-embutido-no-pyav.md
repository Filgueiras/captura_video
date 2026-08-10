# ADR-0020 — Reparar o ALSA embutido no PyAV

**Estado:** Aceito
**Data:** 2026-08-02

## Contexto

Na primeira execução em Linux (Zorin OS 18, Ubuntu 24.04 "noble") a captura de
vídeo funcionou de primeira, mas **toda gravação saía muda** — e sem erro. O
arquivo abria normalmente, com o vídeo intacto e nenhuma faixa de áudio. A única
pista aparecia no terminal, antes de qualquer mensagem do programa:

```
ALSA lib conf.c:4580: Cannot access file /tmp/vendor/share/alsa/alsa.conf
ALSA lib pcm.c:2722:  Unknown PCM hw:2,0
```

`/tmp/vendor` é o diretório de build da máquina que compilou o wheel do PyAV. O
wheel traz a sua própria cópia estática do alsa-lib, e essa cópia carrega o
prefixo de compilação embutido. Fora daquela máquina o caminho não existe, então
a biblioteca sobe **sem configuração nenhuma**: sem a config, o alsa-lib não sabe
traduzir nem `hw:2,0`, e todo dispositivo vira "Unknown PCM".

O problema é do wheel, não do sistema: o `ffmpeg` de linha de comando instalado
pelo apt abre os mesmos dispositivos sem reclamar, porque usa o alsa-lib do
sistema, com o prefixo correto.

Agrava a situação o fato de este wheel **não trazer o demuxer `pulse`**
(`av.formats_available` lista `alsa`, `x11grab`, `kmsgrab`, mas não `pulse`).
O [0002](0002-ffmpeg-embutido-via-pyav.md) já previa que o conjunto de demuxers
varia por wheel, e a `formato_entrada_audio()` já cai para ALSA quando o `pulse`
falta. Só que o caminho de fallback estava, ele próprio, quebrado — restando
nenhuma via de áudio funcional no Linux.

## Decisão

Apontar o alsa-lib embutido para os arquivos do sistema, definindo duas
variáveis de ambiente na importação do pacote
([`capturador/__init__.py`](../../capturador/__init__.py)):

| Variável | Valor | Sem ela |
|---|---|---|
| `ALSA_CONFIG_PATH` | `/usr/share/alsa/alsa.conf` | todo dispositivo é "Unknown PCM" |
| `ALSA_PLUGIN_DIR` | `/usr/lib/<arch>-linux-gnu/alsa-lib` (e equivalentes) | `hw:N,0` abre, mas `default` e `pulse` falham |

A segunda importa mais do que parece. Nesta família de distribuições `default`
não é um dispositivo: é um atalho para o plugin do PipeWire/PulseAudio, que mora
num `.so` fora da cópia embutida. Com `ALSA_PLUGIN_DIR` definido, os PCMs
`default` e `pulse` passam a abrir — **e é por aí que se captura qualquer fonte
do sistema**, recuperando na prática o que a ausência do demuxer `pulse` tirou.

Três cuidados na implementação:

- **Roda na importação do pacote**, não no `main()`. Precisa acontecer antes do
  primeiro `av.open`, e importar `capturador` é o único ponto por onde todos os
  caminhos de entrada passam: a janela, a linha de comando e o executável
  empacotado ([0018](0018-empacotar-com-pyinstaller-em-modo-pasta.md)).
- **Não sobrescreve variável já definida.** Quem apontou para outro lugar tinha
  um motivo, e adivinhar contra o usuário é pior que não fazer nada.
- **Só define o que existe.** Cada caminho é verificado antes; a lista cobre
  Debian/Ubuntu/Zorin, Fedora/openSUSE e Arch, e a arquitetura vem de
  `platform.machine()` em vez de `x86_64` fixo.

## Consequências

- O áudio grava no Linux. Medido nesta máquina após a correção: `pcm_s16le`,
  8,00 s de áudio contra 8,00 s de vídeo, **−2,7 ms de desencontro** — dentro do
  que a âncora de relógio do [0005](0005-sincronia-por-ancora-de-relogio.md)
  promete.
- É uma correção de sintoma, não de causa: se um wheel futuro do PyAV vier com o
  prefixo certo, ou com o demuxer `pulse` próprio, este código vira inofensivo em
  vez de desnecessário — ele apenas confirma caminhos que já estariam certos.
- Efeito colateral no processo inteiro, não só no PyAV. Aceitável porque os
  valores apontam para a configuração legítima do sistema, que é o que qualquer
  outra biblioteca de áudio já usaria.
- Misturar o alsa-lib embutido com plugins `.so` do sistema é, em teoria, um
  risco de ABI. Na prática funciona porque a interface de plugin do ALSA é
  estável há mais de uma década. Testado aqui sem falha.

## Alternativas consideradas

**Compilar o PyAV contra o FFmpeg do sistema** (`pip install av --no-binary av`).
Resolve na raiz e ainda traria o demuxer `pulse` de verdade. Descartada pelo
custo de instalação: exige toolchain de C e os headers de desenvolvimento do
FFmpeg, o que contraria o [0002](0002-ffmpeg-embutido-via-pyav.md) — cuja razão
de ser é não pedir nada além de `pip install`.

**Definir as variáveis no `capturar.sh`.** Mais simples e mais visível, mas só
protege quem abre por ali. Quem roda `python -m capturador`, importa o pacote de
outro script ou usa o executável empacotado continuaria mudo.

**Chamar `ffmpeg` de linha de comando para o áudio.** O binário do sistema não
tem o problema. Mas trocaria uma variável de ambiente por um subprocesso, um
formato de pipe e o fim do controle sobre os tempos dos pacotes, que é
justamente do que a sincronia depende.

**Aceitar só `hw:N,0` e não definir `ALSA_PLUGIN_DIR`.** Bastaria para a placa de
captura, que é o caso de uso principal e é o que o pareamento do
[0011](0011-parear-video-e-audio-pelo-aparelho.md) entrega. Mas deixaria de fora
qualquer outra fonte — microfone gerido pelo PipeWire, por exemplo — sem ganho
nenhum em troca.
