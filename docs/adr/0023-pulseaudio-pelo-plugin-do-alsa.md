# ADR-0023 — Alcançar o PulseAudio pelo plugin do alsa-lib

**Estado:** Aceito
**Data:** 2026-09-18

## Contexto

O [0022](0022-audio-do-computador-por-wasapi.md) resolveu, no Windows, gravar o
som que sai pelas caixas. O README anunciava o equivalente no Linux — a fonte
`.monitor` do PulseAudio/PipeWire — mas ele **nunca funcionou nesta plataforma**,
e a interface mostrava permanentemente *«Áudio do computador (indisponível)»*.

A cadeia que falhava:

1. `formato_entrada_audio()` só escolhia o demuxer `pulse` se ele existisse em
   `av.formats_available`. Os wheels do PyAV não são compilados com libpulse;
   medido em PyAV 18.0.0 no Zorin 18, a lista inteira de demuxers de captura é
   `alsa`, `x11grab`, `kmsgrab` e `video4linux2,v4l2`. Nunca `pulse`.
2. Logo o programa caía sempre para ALSA, e a enumeração ALSA lê
   `/proc/asound/cards`, que só conhece placas físicas.
3. **ALSA não tem monitor de saída.** Sem passar pelo servidor de som não existe
   como capturar o que está tocando.

O [0020](0020-reparar-o-alsa-embutido-no-pyav.md) já havia notado a ausência do
demuxer `pulse` e já apontava a saída — "com `ALSA_PLUGIN_DIR` definido, os PCMs
`default` e `pulse` passam a abrir, e é por aí que se captura qualquer fonte do
sistema" —, mas a enumeração nunca foi ligada nesse caminho: ela continuava
oferecendo só `default` e `hw:N,0`.

Havia ainda um defeito latente que teria estragado a correção: **a saída do
`pactl` é traduzida**. Num desktop em português ele escreve `Fonte #53` e `Nome:`
onde as regex do módulo esperavam `Source #53` e `Name:`. O pareamento por nome
não achava nada — e o público-alvo deste programa usa o sistema em português.

## Decisão

Alcançar as fontes do servidor de som pelo **plugin `pulse` do alsa-lib**,
mantendo o demuxer `alsa` do FFmpeg.

A configuração do sistema declara esse PCM aceitando o nome da fonte como
argumento (`pcm.pulse { @args [ DEVICE ] }`, em
`/usr/share/alsa/alsa.conf.d/50-pulseaudio.conf`). Então `pulse:<fonte>` aberto
pelo demuxer `alsa` chega exatamente na mesma fonte que o demuxer `pulse`
abriria — monitores de saída incluídos.

`via_audio_linux()`, em [`dispositivos.py`](../../capturador/dispositivos.py),
passa a distinguir três vias, da melhor para a pior:

| Via | Demuxer | Caminho | Quando |
|---|---|---|---|
| `VIA_PULSE_DEMUXER` | `pulse` | `<fonte>` | wheel do PyAV com libpulse (raro) |
| `VIA_PULSE_ALSA` | `alsa` | `pulse:<fonte>` | o caso normal em Ubuntu/Zorin |
| `VIA_ALSA` | `alsa` | `hw:N,0` | sem servidor de som |

Junto, duas correções que a decisão exigia:

- **`_rodar` força `LC_ALL=C`.** Todas as regex do módulo foram escritas contra
  a saída em inglês; o locale muda as mensagens do programa, não os nomes dos
  dispositivos, que continuam chegando em UTF-8.
- **O monitor da saída padrão vem primeiro**, lido de `pactl get-default-sink`,
  como o WASAPI já fazia com *«— saída padrão»*. Uma máquina com HDMI e caixas
  tem dois monitores, e o que não está tocando entrega silêncio digital — o
  defeito mais difícil de perceber antes de a gravação acabar.

## Consequências

- **O «Áudio do computador» passa a existir no Linux**, sem instalar driver, sem
  privilégio e sem trocar o dispositivo de reprodução padrão. Medido: gravando
  um tom de 440 Hz a 0,4 de amplitude pela saída, o monitor entregou pico
  `0.4000` — o sinal exato, pelo caminho do próprio programa.
- **O pareamento placa↔áudio melhorou de tabela.** Antes ele apontava para
  `hw:N,0`, passando por cima do PipeWire; agora aponta para a fonte que o
  servidor publica. Medido no mesmo aparelho: `hw:2,0` entrega 96,0% das
  amostras em tempo real mesmo sem carga nenhuma, enquanto `pulse:<fonte>`
  entrega 100,0%.
- **Os nomes na lista ficaram legíveis.** Vinha
  `alsa_output.pci-0000_00_1f.3.analog-stereo.monitor`; passa a vir a descrição
  que o servidor publica, sem o prefixo "Monitor of" que a interface já
  acrescenta à sua maneira.
- Depende de um pacote a mais estar presente: `libasound2-plugins`, que traz o
  `libasound_module_pcm_pulse.so`. Ele acompanha qualquer instalação de desktop
  em Debian/Ubuntu/Zorin, mas a verificação é explícita, e `dica_loopback()`
  diagnostica qual dos três elos quebrou em vez de mandar o usuário conferir os
  três.
- Continua sendo, como o [0020](0020-reparar-o-alsa-embutido-no-pyav.md),
  **correção de sintoma**: um wheel futuro do PyAV com libpulse faz a primeira
  via passar a valer sozinha, sem mudar mais nada.
- Misturar o alsa-lib embutido no wheel com um plugin `.so` do sistema é, em
  teoria, risco de ABI — a mesma aposta que o 0020 já fez, e pelo mesmo motivo:
  a interface de plugin do ALSA é estável há mais de uma década.

## Alternativas consideradas

**Usar a `soundcard` no Linux, como no Windows.** Ela fala PulseAudio e resolveria
o loopback. Descartada porque traria um segundo caminho de áudio para manter, com
relógio próprio (o [0022](0022-audio-do-computador-por-wasapi.md) precisou de um
laço inteiro só para o WASAPI), quando o caminho do PyAV já funciona e entrega os
carimbos de tempo que a âncora do [0005](0005-sincronia-por-ancora-de-relogio.md)
usa.

**Compilar o PyAV contra o FFmpeg do sistema.** Resolve na raiz e traz o demuxer
`pulse` de verdade. Descartada pelo mesmo motivo do 0020: exige toolchain de C e
os headers do FFmpeg, contra a razão de ser do
[0002](0002-ffmpeg-embutido-via-pyav.md).

**Definir `PULSE_SOURCE` antes de cada abertura.** O plugin respeita essa
variável, o que dispensaria o prefixo no caminho. Descartada porque variável de
ambiente é estado global do processo: duas aberturas simultâneas — que é
exatamente o que a monitoração e a gravação fazem — disputariam o mesmo valor.

**O plugin `pipewire` em vez do `pulse`.** Existe e abre (`pcm.pipewire`), mas
recebe a fonte como o segundo de nove argumentos posicionais, contra um só do
`pulse`, e só está presente onde o PipeWire é o servidor — enquanto o `pulse`
funciona nos dois. Medido, entregam o mesmo: blocos de 128 amostras a 100%.
