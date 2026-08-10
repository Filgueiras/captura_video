# Como encontrar e identificar a placa de captura USB

Guia prático para localizar a placa, descobrir o que ela realmente entrega e
diagnosticar problemas — no **Windows** e no **Linux**.

As seções marcadas com **[medido]** contêm dados colhidos diretamente da placa
que está nesta máquina (26/07/2026). O resto é procedimento genérico, que vale
para qualquer dongle de captura USB.

---

## 1. O que é essa placa **[medido]**

A "IT-Blue" é uma marca de revenda. O que importa é o chip por dentro, e ele foi
identificado pelo par VID/PID que o Windows reporta:

```
USB\VID_534D&PID_2109&MI_00
```

| Campo | Valor | Significado | Confiança |
|---|---|---|---|
| VID | `534D` | MacroSilicon | **verificado** — consta na base `usb.ids` |
| PID | `2109` | MS2109 | **inferido** — veja 1.1 |
| MI_00 | — | interface 0 do dispositivo composto (o vídeo) | verificado |

O **MS2109** é o conversor HDMI→USB mais comum do mercado de dongles baratos.
Características que definem tudo o que dá para fazer com ele — todas
**confirmadas por medição** neste guia, independentemente do nome do chip:

- É um **dispositivo composto**: expõe funções de **vídeo (UVC)** e **áudio
  (UAC)** separadas. Por isso aparece como *dois* dispositivos no sistema, não um.
  (Na verdade quatro interfaces — veja 1.2.)
- É **USB 2.0** (480 Mbit/s teóricos, ~320 Mbit/s reais). Mas o gargalo real não
  é a banda: é o compressor JPEG interno, que trava em ~1 megapixel a 60 Hz
  (seção 4.0.1).
- É **class-compliant**: não precisa de driver em nenhum sistema operacional.
  Windows, Linux e macOS reconhecem sozinhos.
- Aceita **um programa por vez**. Se o VLC estiver com ele aberto, mais nada
  consegue abrir.
- **Não deriva**: o relógio de áudio ficou em 48000,0 Hz medidos, ~2 ms/hora de
  descolamento (seção 7).

> Não confunda com o **MS2130** (PID `2130`), que é USB 3.0 e faz 1080p60 sem
> compressão. Se a sua fizer 1080p60 real em YUV, é um 2130, não um 2109.

### 1.1 De onde vem essa identificação

Não existe uma API oficial da USB-IF aberta para consulta de VID/PID. O que
existe, e é o padrão de fato do mundo Linux, é o arquivo **`usb.ids`**: uma base
mantida pela comunidade, usada pelo próprio `lsusb` para traduzir os números em
nomes.

- Fonte: <http://www.linux-usb.org/usb.ids> (texto puro, ~730 KB, domínio público)
- Página do projeto: <http://www.linux-usb.org/usb-ids.html>
- No Linux ela já está em disco, normalmente em `/usr/share/hwdata/usb.ids`
  ou `/var/lib/usbutils/usb.ids`

Consultando essa base diretamente:

```bash
grep -A3 '^534d' /usr/share/hwdata/usb.ids
```

```powershell
# Windows: baixe e procure
Invoke-WebRequest http://www.linux-usb.org/usb.ids -OutFile usb.ids
Select-String -Path usb.ids -Pattern '^534d' -Context 0,3
```

Resultado real da consulta:

```
534d  MacroSilicon
	0021  MS210x Video Grabber [EasierCAP]
	6021  VGA Display Adapter
```

**Duas conclusões honestas, porque elas não têm o mesmo peso:**

1. **O fabricante está confirmado.** `534D` = MacroSilicon, direto da base.
2. **O modelo exato não está.** O PID `2109` **não** aparece no `usb.ids` — só
   `0021` e `6021` estão catalogados. Dizer "MS2109" é uma **inferência**, apoiada
   em três indícios que se reforçam:
   - a MacroSilicon nomeia seus PIDs com o número do modelo (`2130` → MS2130), e
     a própria entrada `0021` já se chama "MS210**x**", confirmando a família;
   - o comportamento medido bate com o MS2109 documentado: USB 2.0, MJPEG
     1080p, YUYV limitado a 5 fps;
   - o mesmo `534d:2109` é o par relatado pela comunidade para esse dongle.

Para a prática não muda nada — o que decide a configuração são os formatos
enumerados na seção 4, e esses foram lidos do hardware. Mas se você precisar da
certeza absoluta do modelo, a única fonte definitiva é a serigrafia do chip
dentro do dongle.

### 1.2 O que a própria placa diz de si **[medido]**

Vale perguntar ao hardware diretamente — o descritor `iProduct` é a string que o
dispositivo publica sobre si mesmo, sem intermediários:

```powershell
Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -like '*VID_534D*' } |
  ForEach-Object {
    $d = Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName 'DEVPKEY_Device_BusReportedDeviceDesc'
    "{0,-46} {1}" -f $_.InstanceId, $d.Data
  }
```

```bash
lsusb -v -d 534d:2109 2>/dev/null | grep -E 'iManufacturer|iProduct|bcdDevice'
```

Resultado:

```
USB\VID_534D&PID_2109\5&399DE990&0&7        USB Video     <- dispositivo composto
USB\VID_534D&PID_2109&MI_00\...             USB Video     <- vídeo (UVC)
USB\VID_534D&PID_2109&MI_02\...             USB Digital Audio   <- áudio (UAC)
USB\VID_534D&PID_2109&MI_04\...             USB Video     <- HID proprietário
HID\VID_534D&PID_2109&MI_04\...             (usage page FF00)
```

**A placa não se identifica como MacroSilicon nem como MS2109 em lugar nenhum.**
Ela se chama apenas "USB Video". Todos os nomes de fabricante que o Windows
exibe ("Microsoft", "Áudio USB genérico") vêm dos drivers class-compliant do
próprio sistema, não do hardware.

Ou seja: o único vínculo com a MacroSilicon é o VID na base `usb.ids`. É um
vínculo sólido — VIDs não são reutilizados —, mas é o único que existe sem abrir
o aparelho.

Dois achados extras:

- **`REV_2100`** — o `bcdDevice`, versão 21.00 do firmware/revisão.
- **Quatro interfaces**, não duas. Além de vídeo (`MI_00`) e áudio (`MI_02`),
  existe uma interface **HID proprietária** (`MI_04`, *usage page* `FF00`, que é
  a faixa reservada para uso do fabricante). É por ela que os utilitários da
  MacroSilicon conversam com o chip para configuração e atualização de firmware.
  Ela é inofensiva e não interfere na captura — mas explica por que a placa
  aparece no Windows também como "Dispositivo USB de Introdução de Texto".

**A verificação definitiva do modelo continua sendo abrir o dongle e ler a
serigrafia do chip.** É o único método que não depende de inferência.

> Outras bases que espelham o mesmo dado, com interface de busca:
> [devicehunt.com](https://devicehunt.com/all-usb-vendors) e
> [the-sz.com/products/usbid](https://www.the-sz.com/products/usbid/).
> Todas derivam do `usb.ids` — não são fontes independentes.

---

## 2. Windows

### 2.1 Confirmar que o sistema vê a placa

**Gerenciador de Dispositivos** (`devmgmt.msc`) — procure em duas categorias
diferentes, porque é um dispositivo composto:

- **Câmeras** → `USB Video`
- **Controladores de som, vídeo e jogos** → `USB Digital Audio`

**PowerShell** — mais rápido e mostra o estado:

```powershell
Get-PnpDevice -PresentOnly |
  Where-Object { $_.Class -in 'Camera','MEDIA','AudioEndpoint' } |
  Select-Object Class, FriendlyName, Status | Format-Table -AutoSize
```

Resultado nesta máquina **[medido]**:

```
Camera         USB Video                                          OK
MEDIA          USB Digital Audio                                  OK
AudioEndpoint  Interface de áudio digital (2- USB Digital Audio)  OK
```

### 2.2 Descobrir o VID/PID (para identificar o chip)

```powershell
Get-PnpDevice -PresentOnly -Class Camera |
  Select-Object FriendlyName, InstanceId | Format-List
```

O `InstanceId` traz o `VID_xxxx&PID_xxxx`. Foi assim que o MS2109 foi
identificado aqui.

### 2.3 Listar os nomes exatos para captura

O Windows usa **DirectShow**. Os nomes precisam bater caractere por caractere —
inclusive acentos:

```powershell
ffmpeg -hide_banner -f dshow -list_devices true -i dummy
```

Saída nesta máquina **[medido]**:

```
"USB Video" (video)
"OBS Virtual Camera" (none)
"Microfone (Realtek(R) Audio)" (audio)
"Interface de áudio digital (2- USB Digital Audio)" (audio)
```

Note que o áudio da placa **não** se chama "USB Video" nem nada parecido: em
Windows em português ele vira `Interface de áudio digital (...)`. É um erro
comum procurar por "HDMI" e não achar nada.

### 2.4 Listar os formatos que ela aceita — o passo que resolve tudo

```powershell
ffmpeg -hide_banner -f dshow -list_options true -i video="USB Video"
ffmpeg -hide_banner -f dshow -list_options true -i audio="Interface de áudio digital (2- USB Digital Audio)"
```

### 2.5 Se o sistema não mostrar a placa

1. **Privacidade** — Configurações → Privacidade → Câmera → ative
   "Permitir que aplicativos da área de trabalho acessem sua câmera".
   Sem isso a placa existe no Gerenciador mas não abre em nada.
2. **Porta** — use uma porta USB traseira, ligada direto na placa-mãe.
   Hub passivo com outros periféricos rouba banda e derruba a taxa de quadros.
3. **Cabo** — cabo USB longo ou de má qualidade causa desconexão intermitente.
4. **Sem sinal HDMI** — sem fonte conectada, a placa aparece mas entrega tela
   preta ou nem abre. Teste com a fonte ligada.

---

## 3. Linux

### 3.1 Confirmar no barramento USB

```bash
lsusb | grep -i -E '534d|macrosilicon'
```

Saída esperada (o texto varia conforme a versão do `usb.ids`):

```
Bus 001 Device 007: ID 534d:2109 MACROSILICON USB Video
```

Se o nome não aparecer, o ID `534d:2109` já é suficiente para identificar.

Para ver a árvore e confirmar em que velocidade ela negociou:

```bash
lsusb -t
```

Procure a linha da placa. Deve dizer `480M` (USB 2.0 High Speed). Se disser
`12M`, ela caiu para Full Speed — troque de porta ou de cabo, porque nessa
velocidade não sai vídeo utilizável.

Detalhes completos do descritor, incluindo os formatos declarados:

```bash
lsusb -v -d 534d:2109 | less
```

E o que o kernel registrou ao conectar:

```bash
sudo dmesg | grep -i -E 'uvcvideo|snd-usb|534d'
```

### 3.2 Achar o nó de vídeo

O Linux cria `/dev/videoN`. Uma mesma placa costuma criar **dois** nós: um de
captura e um só de metadados — só o primeiro serve.

```bash
v4l2-ctl --list-devices
```

Saída típica para esta placa:

```
USB Video: USB Video (usb-0000:00:14.0-4):
        /dev/video0
        /dev/video1
```

Confirmar qual é o de captura de verdade:

```bash
v4l2-ctl --device=/dev/video0 --all | grep -A3 'Video Capture'
```

Se `v4l2-ctl` não estiver instalado:

```bash
sudo apt install v4l-utils        # Debian/Ubuntu
sudo dnf install v4l-utils        # Fedora
sudo pacman -S v4l-utils          # Arch
```

Alternativa sem instalar nada — o nome fica exposto no sysfs:

```bash
for d in /sys/class/video4linux/video*; do
  echo "$d -> $(cat $d/name)"
done
```

### 3.3 Listar os formatos — o equivalente do passo 2.4

```bash
v4l2-ctl --device=/dev/video0 --list-formats-ext
```

Saída no formato:

```
ioctl: VIDIOC_ENUM_FMT
        Type: Video Capture

        [0]: 'MJPG' (Motion-JPEG, compressed)
                Size: Discrete 1920x1080
                        Interval: Discrete 0.017s (60.000 fps)
                ...
        [1]: 'YUYV' (YUYV 4:2:2)
                Size: Discrete 1920x1080
                        Interval: Discrete 0.200s (5.000 fps)
                ...
```

**É exatamente essa lista que decide a qualidade da imagem.** Veja a seção 4.

### 3.4 Achar a entrada de áudio

A placa registra uma placa de som ALSA própria:

```bash
arecord -l
cat /proc/asound/cards
```

Saída típica:

```
card 1: MS2109 [MACROSILICON USB Digital Audio], device 0: USB Audio [USB Audio]
```

O número do card é o que importa: ele vira `hw:1,0` nos comandos.

Com PulseAudio/PipeWire:

```bash
pactl list short sources | grep -i -E 'usb|ms2109|macrosilicon'
```

> Ignore as fontes terminadas em `.monitor` — elas são a *saída* do seu PC.
> Gravar uma delas causa eco e não captura o HDMI.

### 3.5 Permissões

Se der `Permission denied` ao abrir `/dev/video0`:

```bash
sudo usermod -aG video $USER
```

Depois **saia e entre na sessão de novo** (o grupo só vale em sessão nova).
Para áudio via ALSA, o grupo é `audio`.

### 3.6 Descobrir quem está segurando a placa

O erro "Device or resource busy" vem de outro programa com o dispositivo aberto:

```bash
sudo fuser -v /dev/video0
# ou
sudo lsof /dev/video0
```

---

## 4. Os modos reais desta placa **[medido]**

Enumerados diretamente do hardware. Esta tabela é o coração de todo o
diagnóstico:

| Formato | Resolução | Taxa **anunciada** |
|---|---|---|
| **MJPEG** | **1920x1080** | **60 fps** (real: 30 — veja 4.0) |
| MJPEG | 1600x1200 | 60 fps |
| MJPEG | 1280x1024 / 1280x960 / 1360x768 | 60 fps |
| MJPEG | 1280x720 | 60 fps |
| MJPEG | 1024x768 / 800x600 / 720x576 / 720x480 / 640x480 | 60 fps |
| YUYV (sem compressão) | 1920x1080 | **5 fps** |
| YUYV | 1600x1200 | 5 fps |
| YUYV | 1360x768 / 1280x1024 / 1280x960 | 8 fps |
| YUYV | 1280x720 / 1024x768 | 10 fps |
| YUYV | 800x600 | 20 fps |
| YUYV | 720x480 / 640x480 | 30 fps |

Áudio (`Interface de áudio digital`), 16 bits, mono ou estéreo:

```
8000 · 11025 · 22050 · 32000 · 44100 · 48000 · 96000 Hz
```

### 4.0 A taxa anunciada é mentira: 60 fps declarados, 30 fps reais **[medido]**

A placa declara 60 fps a 1080p, mas **não consegue gerar 60 quadros**. Em vez de
anunciar 30, ela mantém a cadência de 60 e preenche a metade que falta com
**quadros JPEG vazios de 4 bytes** — apenas os marcadores de início e fim de
imagem (`FF D8 FF D9`), sem conteúdo nenhum.

Inspecionando os pacotes brutos capturados (isto veio de uma gravação feita com
`ffmpeg` puro, sem nenhum código intermediário):

```
pacote 0: tamanho=     4 bytes   início=ffd8ffd9   <- vazio
pacote 1: tamanho= 76477 bytes   início=ffd8ffdb   <- quadro real
pacote 2: tamanho=     4 bytes   início=ffd8ffd9   <- vazio
pacote 3: tamanho= 76610 bytes   início=ffd8ffdb   <- quadro real
```

Um real, um vazio, alternando. **A taxa útil é exatamente metade: 30 fps.**

Consequências práticas:

- O `ffmpeg` reclama `No JPEG data found in image` a cada quadro vazio. **Isso é
  normal com esta placa** e não indica defeito nem cabo ruim.
- Se esses pacotes forem gravados junto, o arquivo final fica cheio de erros de
  decodificação — metade dos quadros é inválida. Foi o que aconteceu no primeiro
  teste deste projeto, até o filtro ser adicionado.
- Pedir `-framerate 30` em vez de 60 **não** resolve: a placa continua mandando o
  mesmo fluxo alternado.

A solução é descartar todo pacote menor que alguns centenas de bytes antes de
gravar ou decodificar. Nenhum quadro 1080p real chega perto disso — os reais têm
~76 KB. O aplicativo deste repositório faz isso automaticamente
([captura.py](capturador/captura.py), constante `_MIN_BYTES_JPEG`), e por isso
grava arquivos que decodificam sem um único erro.

Para gravar pela linha de comando sem o problema, o filtro equivalente é
recodificar em vez de copiar (aí o decodificador simplesmente ignora os vazios):

```powershell
ffmpeg -f dshow -vcodec mjpeg -video_size 1920x1080 -framerate 60 -i video="USB Video" `
       -c:v libx264 -crf 20 -r 30 saida.mp4
```

O custo é perder a cópia sem recompressão. Preservar as duas coisas ao mesmo
tempo — cópia direta **e** arquivo limpo — exige filtrar pacote a pacote, que é
o que o aplicativo faz.

### 4.0.1 Onde exatamente fica o limite **[medido]**

Medindo todos os 11 modos MJPEG, 3 segundos cada, contando separadamente os
quadros com imagem e os de enchimento (`python -m capturador --medir`):

| Modo | Pixels | Anunciado | **Real** | Vazios | Mbit/s |
|---|---:|---:|---:|---:|---:|
| 1920x1080 | 2,07 MP | 60 | **30,5** | 50% | 18,7 |
| 1600x1200 | 1,92 MP | 60 | **30,3** | 50% | 17,4 |
| 1280x1024 | 1,31 MP | 60 | **30,3** | 50% | 12,8 |
| 1280x960 | 1,23 MP | 60 | **29,9** | 50% | 12,0 |
| 1360x768 | 1,04 MP | 60 | **29,9** | 50% | 10,8 |
| **1280x720** | **0,92 MP** | 60 | **59,8** | — | 19,5 |
| 1024x768 | 0,79 MP | 60 | **59,8** | — | 17,7 |
| 800x600 | 0,48 MP | 60 | **59,8** | — | 11,8 |
| 720x576 | 0,41 MP | 60 | **59,8** | — | 10,5 |
| 720x480 | 0,35 MP | 60 | **59,8** | — | 9,3 |
| 640x480 | 0,31 MP | 60 | **59,8** | — | 8,7 |

**A fronteira é 1 megapixel por quadro.** Até 0,92 MP (1280x720) a placa entrega
60 fps de verdade, sem um único quadro vazio. A partir de 1,04 MP (1360x768) ela
cai para exatamente metade. Não há meio-termo: é 60 ou 30, nunca 45.

E **não é falta de banda USB**: o pico medido foi 19,5 Mbit/s, contra os ~320
Mbit/s úteis do USB 2.0. Sobra banda de sobra. O gargalo é o compressor JPEG
dentro do chip, que não sustenta mais de ~1 MP a 60 Hz.

#### O que isso significa na prática

Só existem **dois** modos que valem a pena nesta placa:

| Objetivo | Escolha | Por quê |
|---|---|---|
| Movimento fluido (jogos, vídeo, esporte) | **1280x720 @ 60 fps** | 60 fps reais, medidos |
| Detalhe e texto (slides, código, câmera fixa) | **1920x1080 @ 30 fps** | resolução máxima real |

E uma armadilha: **1360x768, 1280x960, 1280x1024 e 1600x1200 são estritamente
piores que as duas opções acima.** Eles rodam a 30 fps *e* têm menos resolução
que 1080p. Não há situação em que compensem — parecem opções intermediárias, mas
não são: você paga a queda para 30 fps sem receber a resolução em troca.

> Para conferir na sua própria placa, que pode ter outro chip:
> ```
> python -m capturador --medir
> ```

### 4.1 Por que o VLC entrega imagem ruim

Olhe a tabela. A placa oferece dois caminhos e eles são **radicalmente**
diferentes:

- **MJPEG** — comprimido dentro da placa. 1080p a 60 fps cabe folgado no USB 2.0.
- **YUYV** — sem compressão. 1080p60 em YUYV exigiria ~3 Gbit/s, quase 10x mais
  do que o USB 2.0 aguenta. Então o firmware trava em **5 fps**.

Players genéricos negociam o formato "mais simples" e acabam em YUYV. Aí só há
duas saídas ruins: aceitar 1080p a 5 fps (imagem travando), ou cair para uma
resolução onde o YUYV alcança 30 fps — **720x480 ou 640x480**. É esse segundo
caso que dá a sensação de "qualidade ruim": a imagem está sendo esticada de
640x480 para a sua tela.

**A placa não é o problema. A negociação de formato é.**

### 4.2 Corrigindo no próprio VLC

Se quiser continuar usando VLC, force o modo na abertura:

- Interface: *Mídia → Abrir dispositivo de captura* → em **Opções avançadas**,
  preencha `Tamanho do vídeo` = `1920x1080` e `Taxa de quadros` = `60`.
- Linha de comando (Windows):

```powershell
vlc dshow:// --dshow-vdev="USB Video" --dshow-adev="Interface de áudio digital (2- USB Digital Audio)" --dshow-size=1920x1080 --dshow-fps=60 --dshow-chroma=MJPG
```

- Linha de comando (Linux):

```bash
vlc v4l2:///dev/video0:chroma=MJPG:width=1920:height=1080:fps=60
```

O `--dshow-chroma=MJPG` / `chroma=MJPG` é a parte que realmente importa.

---

## 5. Testes rápidos de linha de comando

### Windows

```powershell
# Só ver a imagem, no modo certo
ffplay -f dshow -vcodec mjpeg -video_size 1920x1080 -framerate 60 -i video="USB Video"

# Medir a taxa de quadros real durante 10 s
ffmpeg -f dshow -vcodec mjpeg -video_size 1920x1080 -framerate 60 -i video="USB Video" -t 10 -f null -

# Gravar 30 s de vídeo + áudio sem recomprimir nada
ffmpeg -f dshow -vcodec mjpeg -video_size 1920x1080 -framerate 60 -i video="USB Video" `
       -f dshow -sample_rate 48000 -channels 2 -i audio="Interface de áudio digital (2- USB Digital Audio)" `
       -c copy -t 30 teste.mkv
```

### Linux

```bash
# Só ver a imagem
ffplay -f v4l2 -input_format mjpeg -video_size 1920x1080 -framerate 60 -i /dev/video0

# Medir a taxa real
ffmpeg -f v4l2 -input_format mjpeg -video_size 1920x1080 -framerate 60 -i /dev/video0 -t 10 -f null -

# Gravar sem recomprimir
ffmpeg -f v4l2 -input_format mjpeg -video_size 1920x1080 -framerate 60 -i /dev/video0 \
       -f alsa -sample_rate 48000 -channels 2 -i hw:1,0 \
       -c copy -t 30 teste.mkv
```

Compare a linha `fps=` no final com o que você pediu. Nesta placa, pedir 60
resulta em **~30 reais** — pelo motivo explicado na seção 4.0, não por falha de
cabo ou de porta. As mensagens `No JPEG data found in image` durante o teste são
esperadas e podem ser ignoradas.

---

## 6. Coisas que confundem, e a explicação

| Sintoma | Causa | O que fazer |
|---|---|---|
| "Dispositivo em uso" / "I/O error" / "Device busy" | A placa aceita **um** programa por vez | Feche VLC, OBS, aba do navegador com câmera, Discord, Teams |
| Imagem estourada/lavada ou escura demais | Faixa de cor: a fonte manda TV (16–235), o software lê como PC (0–255) | Ajuste a faixa RGB na fonte (console/PC) para "Completa", ou corrija no player |
| Áudio fora de sincronia crescendo com o tempo | **Não acontece nesta placa** — medido em ~2 ms/hora | Veja a seção 7 antes de suspeitar disso |
| Áudio com tom errado (grave/agudo demais) | Taxa negociada diferente da real do HDMI | Teste 48000 **e** 96000 e compare de ouvido; use a que soar natural |
| `No JPEG data found in image` sem parar | Quadros de enchimento vazios da própria placa | Normal nesta placa — seção 4.0. Filtre os pacotes curtos |
| Arquivo gravado com metade dos quadros corrompida | Os quadros vazios foram copiados para o arquivo | Descarte pacotes < 256 bytes antes do mux — seção 4.0 |
| Taxa de quadros abaixo do esperado | Nesta placa, 60 anunciados = 30 reais (seção 4.0). Fora isso: fonte HDMI mandando menos, ou USB compartilhado | Confira a saída da fonte; use porta USB traseira exclusiva |
| Só sai 640x480 | Formato negociado é YUYV | Force MJPEG — seção 4.1 |
| Nada aparece, mas o dispositivo existe | Sem sinal HDMI, ou HDCP na fonte | Conteúdo protegido (Netflix, Blu-ray, PS5 em alguns modos) **não** é capturável |

---

## 7. Sincronia entre áudio e vídeo **[medido]**

A preocupação é legítima: vídeo e áudio saem por **endpoints USB separados**, com
relógios que o host trata como independentes. Se um correr mais rápido que o
outro, a diferença se acumula e o áudio descola da imagem em gravações longas.

### 7.1 O que foi medido

Duas medições distintas, porque elas respondem perguntas diferentes.

**A placa deriva?** 240 segundos lendo os dois fluxos em paralelo, comparando o
ritmo de cada um contra o relógio do sistema:

| | Medido | Nominal | Desvio |
|---|---|---|---|
| Vídeo | 30,006 fps | 30 | — |
| Áudio | **48000,0 Hz** | 48000 | **−1 ppm** |
| Carimbos de tempo | 1,0000000× o relógio real | — | ±1 ppm |

**Deriva relativa: ~3 ms por hora.** Desprezível.

**A gravação preserva a sincronia?** Gravação real de 3 minutos pelo aplicativo,
analisando o arquivo final:

```
vídeo termina em : 180,021 s
áudio termina em : 180,021 s
diferença        :   -0,3 ms       <- em 3 minutos
deriva interna do áudio : -1 ppm   => 2 ms/hora
alinhamento inicial     : +17 ms   (áudio levemente atrás)
```

Para referência, a norma **ITU-R BT.1359** define como imperceptível a faixa de
−125 ms (áudio atrasado) a +45 ms (áudio adiantado). Os 17 ms de offset inicial
estão bem dentro, e são **constantes** — não crescem.

**Conclusão: não é preciso se preocupar com deriva nesta placa.** Uma gravação de
8 horas acumularia ~16 ms, um sexto do limiar de percepção.

### 7.2 Uma armadilha na hora de medir isso

Se você for medir por conta própria, cuidado com dois erros que eu cometi antes
de chegar aos números acima:

1. **Dividir o total de amostras pelo tempo decorrido.** Os primeiros pacotes
   trazem o que já estava no buffer do driver antes de você começar a contar.
   Com buffer de 80 ms numa medição de 180 s, isso sozinho aparece como
   **+440 ppm** de deriva inexistente. Use a *inclinação* da reta de amostras
   acumuladas, que ignora o degrau inicial, e descarte os primeiros segundos.
2. **Comparar o carimbo do último pacote de cada fluxo.** Pacotes de áudio têm
   80 ms e quadros de vídeo 33 ms; a diferença entre os inícios dos últimos
   pacotes carrega ±80 ms de puro ruído de quantização. Compare **fim de
   conteúdo**: último carimbo + duração daquele pacote.

Os dois erros produzem "deriva" na casa de 1,5 s/hora que não existe.

### 7.3 O que realmente pode quebrar a sincronia

Nenhum desses é problema de relógio:

- **Travadas do sistema.** Se o disco ou a CPU engasgarem, quadros são perdidos.
  O aplicativo carimba cada pacote pelo tempo real do dispositivo, então um
  quadro perdido vira uma lacuna real na linha do tempo — a imagem "pula" mas
  não descola do áudio. Programas que apenas contam quadros e assumem cadência
  constante deslocam tudo o que vem depois; esse é o modo de falha comum.
- **Relógio da fonte HDMI.** Se o aparelho conectado gera áudio num ritmo
  levemente diferente dos 48 kHz do dongle, o dongle compensa descartando ou
  repetindo amostras. Isso aparece como **estalos ocasionais**, não como deriva.
- **Reencodar depois com parâmetros errados.** Forçar `-r` fixo num material que
  não tem cadência constante desalinha tudo. Se precisar reencodar, use
  `-vsync passthrough` ou `-fps_mode passthrough` para preservar os carimbos.

### 7.4 Como reproduzir a medição

```bash
# duração real de conteúdo de cada fluxo num arquivo gravado
ffprobe -v error -select_streams v:0 -show_entries stream=nb_read_frames,r_frame_rate \
        -count_frames -of default=noprint_wrappers=1 gravacao.mkv
ffprobe -v error -select_streams a:0 -show_entries stream=duration_ts,time_base,sample_rate \
        -of default=noprint_wrappers=1 gravacao.mkv
```

Compare o número de amostras dividido pela taxa com a contagem de quadros
dividida pelo fps. Se baterem dentro de alguns milissegundos, a sincronia está
íntegra.

---

## 8. Atalho: descobrir tudo isso de uma vez

O aplicativo deste repositório faz toda a enumeração acima, nos dois sistemas,
com um comando:

```bash
python -m capturador --listar
```

Ele imprime dispositivos, caminhos, todos os formatos e marca com
`<- recomendado` o modo de maior qualidade real — que é exatamente o que ele
seleciona sozinho ao abrir.
