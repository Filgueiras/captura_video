# ADR-0022 — Gravar o áudio do computador por WASAPI, sem filtro de terceiros

**Estado:** Aceito
**Data:** 2026-08-09

## Contexto

Gravando a tela, o som que interessa é o que sai pelas caixas. E esse som **não
é um dispositivo de captura**: o Windows expõe a saída como *render endpoint*,
não como entrada, e o FFmpeg embutido no PyAV
([0002](0002-ffmpeg-embutido-via-pyav.md)) não tem loopback WASAPI. O demuxer
`dshow` só enumera o que o DirectShow considera entrada.

O efeito prático era o pior possível: escolher "Janela específica" e querer o som
do computador deixava o usuário diante de uma lista onde a resposta certa
simplesmente não existia — sem erro, sem explicação. No Linux o problema era
outro e igualmente autoinfligido: a fonte `.monitor` do PulseAudio é exatamente o
dispositivo certo, e estava sendo **descartada de propósito** na enumeração, com
a justificativa de que capturá-la causa eco.

A saída óbvia era mandar o usuário instalar um filtro DirectShow. Três candidatos
circulam: `virtual-audio-capturer` (do projeto *screen-capture-recorder*),
VB-Cable e a Mixagem estéreo do driver. Investigamos o primeiro, que é o único
que grava a saída padrão sem obrigar o usuário a trocar o dispositivo de
reprodução. **A licença inviabiliza embutir:** a API do GitHub classifica o
repositório como `spdx_id: "NOASSERTION"`, e o arquivo LICENSE abre com

> "Contact me about a (free) open source license. Basically I can release the
> code under 'some license', but it cannot be GPL, or so I'm told."

Ou seja, o autor diz que *poderia* licenciar e pede contato. Não há concessão de
redistribuição. "Free" ali é preço, não licença. Somem-se dois estorvos
independentes da licença: a instalação exige `regsvr32` **como administrador**
(registro COM em HKLM), e filtros DirectShow registrados por terceiros são um
padrão que antivírus sinaliza com frequência.

## Decisão

Falar WASAPI direto, em modo loopback, pela biblioteca
[SoundCard](https://github.com/bastibe/SoundCard) (BSD-3-Clause). Ela usa COM via
`ctypes`, **sem compilar nada**, e não requer driver, instalação nem elevação.

A escolha entra no modelo de dados como um campo `backend` em `DispositivoAudio`
([`dispositivos.py`](../../capturador/dispositivos.py)):

| `backend` | Origem | Como abre |
|---|---|---|
| `BACKEND_DEMUXER` (`""`) | dshow, pulse, alsa | `av.open()`, como sempre |
| `BACKEND_WASAPI` | saída do Windows em loopback | `soundcard.get_microphone(include_loopback=True)` |

No motor, um segundo laço — `_laco_wasapi` — lê blocos de 80 ms e monta um
`av.AudioFrame`. **A partir do quadro montado o caminho é literalmente o mesmo**:
mesmo gravador, mesma âncora de relógio
([0005](0005-sincronia-por-ancora-de-relogio.md)), mesma medição de nível e de
silêncio ([0021](0021-estado-do-audio-pelas-amostras.md)). A diferença é a fonte,
não o destino.

Três decisões menores que vêm junto:

- **O relógio sai da contagem de amostras**, não de carimbos do dispositivo. É um
  relógio melhor que o do dshow: não tem jitter, cada bloco vale exatamente os
  seus quadros, e o WASAPI já repõe com silêncio o que faltar.
- **A âncora ganhou um parâmetro `atraso`.** Um bloco só fica pronto depois de
  gravado inteiro: quando chega, o som que ele carrega começou 80 ms atrás. Sem
  descontar isso, a trilha inteira entrava deslocada por essa constante.
- **No perfil Original o áudio do loopback vira PCM**
  ([0006](0006-dois-perfis-de-gravacao.md)). "Sem recompressão" não pode ser
  cumprido copiando quando não existe pacote comprimido para copiar; PCM é o
  equivalente honesto — é o que o misturador do sistema produziu, e o MKV do
  perfil já o aceita.

Na interface, a fonte de loopback **desabilita "Ouvir o áudio"**. Reproduzir na
saída o que acabou de ser capturado dela devolve o som para dentro da captura, e
cada volta soma. Isso também é o que torna seguro parar de descartar a `.monitor`
no Linux: o eco que justificava o descarte passou a ser impedido do lado certo.

## Consequências

- **Funciona sem instalar nada.** Medido nesta máquina, que não tem nenhum filtro
  DirectShow de loopback: as três saídas apareceram imediatamente, e a captura
  reproduziu um tom de 440 Hz emitido a 0,2 de amplitude com pico de 0,0476 —
  a diferença é o volume do sistema, aplicado antes do ponto de captura.
- Gravação de ecrã + áudio do sistema em H.264, tom tocado 1,000 s depois do
  início: **440,1 Hz** no arquivo, e o tom começa em **0,976 s / 1,028 s /
  1,041 s** em execuções distintas. É esta a medição que interessa para a
  sincronia, e ela mostra o áudio no lugar certo.
- O `desencontro_ms` do relatório de amostra oscilou entre **+29 ms e −116 ms**
  nas mesmas execuções, e isso **não** contradiz o item anterior: ele compara
  fim de trilha com fim de vídeo, e a trilha perde o bloco em voo quando a
  gravação para (até 80 ms) mais o resto da FIFO menor que um quadro AAC (até
  21 ms). Não é viés — numa das medições o áudio saiu mais *longo* que o vídeo.
  Quem quiser encurtar essa faixa mexe no bloco de leitura, não na âncora.
- Placa (MJPEG copiado) + áudio do computador no perfil Original: `mjpeg +
  pcm_s16le`, amplitude preservada exatamente (0,500 emitido, 0,500 gravado),
  439,9 Hz, −11 ms de desencontro.
- **Uma dependência nova**, só no Windows (`sys_platform == "win32"` em
  `requisitos.txt`). Escolhida também por não compilar: o Python desta máquina é
  o 3.14, e wheels compilados costumam demorar a acompanhar.
- **Furamos a fronteira do [0003](0003-fronteira-de-plataforma-em-dispositivos.md).**
  `captura.py` agora tem um laço que importa `soundcard`, e o 0003 diz que código
  específico de sistema mora em `dispositivos.py`. A fronteira foi preservada
  onde dava — a enumeração e o `backend` continuam lá — mas o laço de leitura não
  cabe numa dataclass neutra: `entrada()` devolve `(caminho, formato, opções)`
  para `av.open`, e aqui não há `av.open`. É uma exceção consciente, não um
  descuido.
- Duas vias de áudio para manter. Toda mudança no tratamento de som precisa ser
  pensada nas duas, e a segunda só é exercitável no Windows.
- O empacotamento com PyInstaller
  ([0018](0018-empacotar-com-pyinstaller-em-modo-pasta.md)) **não precisou de
  nada**: a SoundCard traz o próprio hook (`soundcard/__pyinstaller`), registrado
  pelo entry point `pyinstaller40`, e ele recolhe os `.py.h` que a `cffi` lê em
  tempo de importação. Verificado num executável congelado de verdade: as três
  saídas enumeradas e um bloco `(3840, 2) float32` gravado do loopback. O
  `capturador.spec` segue sem `hiddenimports`. As advertências
  `pycparser.lextab/yacctab` que aparecem no build são conhecidas e inofensivas.
- A caixa de instruções para habilitar Mixagem estéreo / VB-Cable continua no
  código, mas virou **reserva**: aparece só se o WASAPI não responder.

## Alternativas consideradas

**Embutir o `virtual-audio-capturer` no instalador.** Era o plano inicial e foi
o que motivou a investigação. Barrado pela licença (`NOASSERTION`, sem concessão
de redistribuição). Mesmo com licença, exigiria `regsvr32` com elevação.

**PyAudioWPatch** (MIT), fork do PortAudio com loopback WASAPI. Tecnicamente
adequado e amplamente usado, mas é um wheel compilado e publica até o Python
3.13; o interpretador desta máquina é o 3.14. A SoundCard, sendo `ctypes` puro,
não tem versão de Python para acompanhar.

**Instruir o usuário a habilitar a Mixagem estéreo.** Custo zero de código e foi
o que ficou implementado como primeiro passo antes desta decisão. Descartado como
caminho principal porque depende do driver da placa expor a função — nesta
máquina, com áudio Realtek e NVIDIA HDMI, ela não existe.

**Escrever o cliente WASAPI nós mesmos, em `ctypes`.** Elimina a dependência e é
o que a SoundCard faz por dentro. São algumas centenas de linhas de COM
(`IMMDeviceEnumerator`, `IAudioClient`, `IAudioCaptureClient`) mais tratamento de
formato do misturador e de reconexão de endpoint — muito código para reimplementar
uma biblioteca BSD que já está testada.

**Chamar o `ffmpeg` de linha de comando com algum filtro externo.** Trocaria uma
biblioteca por um subprocesso, um formato de pipe e o fim do controle sobre os
tempos dos pacotes — do qual a sincronia depende. É a mesma razão pela qual o
[0020](0020-reparar-o-alsa-embutido-no-pyav.md) recusou essa saída.
