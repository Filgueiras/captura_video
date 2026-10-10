# Como rodar

Do código-fonte, nos dois sistemas. Para gerar um executável que roda sem Python
instalado, veja [COMO_GERAR_EXECUTAVEL.md](COMO_GERAR_EXECUTAVEL.md).

---

## O que cada sistema precisa

O código é o mesmo nos dois; o que muda é o que o sistema precisa ter em volta.
A tabela é o resumo — cada linha está explicada na seção da sua plataforma.

| | Windows 10/11 | Linux (Zorin 18, Ubuntu 24.04) |
|---|---|---|
| **Dependências Python** | `pip install` direto | **venv obrigatório** — o `pip` do sistema é bloqueado (PEP 668) |
| **FFmpeg de linha de comando** | **necessário** (`winget install Gyan.FFmpeg`) — é o que lista os formatos da placa | não usa; quem lista os formatos é o `v4l2-ctl` |
| **Ferramenta de enumeração** | vem no FFmpeg (`-f dshow -list_options`) | `sudo apt install v4l-utils` |
| **Permissão de acesso à placa** | Configurações → Privacidade → **Câmera** | normalmente já resolvido por ACL; senão, grupo `video` |
| **Áudio** | DirectShow, junto com o vídeo | PulseAudio/PipeWire pelo plugin do alsa-lib; cai para ALSA cru sem servidor de som |
| **Captura de ecrã** | `ddagrab` (Desktop Duplication) — 41 fps aqui | só em sessão **Xorg**; sob Wayland nem é oferecida |
| **Captura de janela** | `gdigrab` | `x11grab -window_id` (usa `x11-utils`, já instalado); sob Wayland, só aplicativos XWayland |
| **Como abrir** | duplo clique em `Captura USB.bat` | `./capturar.sh` |

Duas assimetrias merecem atenção porque contrariam a intuição:

- **O FFmpeg de linha de comando só é necessário no Windows.** Não é
  inconsistência: nos dois sistemas a captura em si usa as bibliotecas embutidas
  no `av`. O binário externo entra só para *perguntar à placa quais formatos ela
  aceita*, e essa pergunta se faz com ferramentas diferentes em cada sistema —
  `ffmpeg -list_options` num, `v4l2-ctl` no outro. Ver
  [ADR-0002](adr/0002-ffmpeg-embutido-via-pyav.md).
- **A captura de ecrã é melhor no Windows.** É o único ponto em que os dois
  sistemas não se equivalem: no Windows o `ddagrab` entrega a tela pronta pela
  mesma via que o OBS usa; no Linux moderno o Wayland fechou o caminho antigo
  (`x11grab`) para o ecrã inteiro, e o substituto exige um protocolo inteiro
  (`xdg-desktop-portal` + PipeWire) ainda não implementado aqui. Captura de
  **janela** escapa dessa limitação sob Wayland, desde que o aplicativo rode
  sobre XWayland.

Para o uso principal — **placa de captura HDMI→USB** — os dois sistemas estão em
pé de igualdade, incluindo o pareamento automático do áudio da placa.

---

## Windows

**1. Python 3.10 ou mais novo.** Em <https://python.org>, marcando
**"Add Python to PATH"** durante a instalação. Confira:

```powershell
python --version
```

**2. Dependências do projeto**, a partir da pasta do projeto:

```powershell
pip install -r requisitos.txt
```

São três: `PySide6` (a interface), `av` (o FFmpeg embutido) e `numpy`.

**3. FFmpeg de linha de comando:**

```powershell
winget install Gyan.FFmpeg
```

**Feche e reabra o terminal** depois de instalar — o `winget` altera o `PATH` e
a sessão aberta não enxerga a mudança. Confira com `ffmpeg -version`.

> **Por que isto é necessário se o FFmpeg já vem embutido no `av`?**
> O `av` traz as *bibliotecas*, que capturam e gravam. Descobrir **quais
> formatos a placa aceita** exige `ffmpeg -f dshow -list_options`, que só existe
> no binário de linha de comando. Ver [ADR-0002](adr/0002-ffmpeg-embutido-via-pyav.md).
>
> Sem ele o programa abre e avisa, mas nenhuma placa aparece na lista.

**4. Permissão de câmera.** Se nenhuma placa aparecer mesmo com o FFmpeg
instalado: **Configurações → Privacidade → Câmera →** ative
**"Permitir que aplicativos da área de trabalho acessem sua câmera"**. O Windows
trata placas de captura como câmeras, e essa chave vem desligada em algumas
instalações.

**5. Abrir:** duplo clique em [`Captura USB.bat`](../Captura%20USB.bat).

O `.bat` prefere o `pythonw` quando existe, que abre a janela **sem** um console
preto atrás dela.

---

## Linux (Ubuntu, Zorin, Debian e derivados)

**1. Pré-requisitos de sistema:**

```bash
sudo apt install python3-venv v4l-utils
```

**`v4l-utils`** é o que permite descobrir os formatos que a placa aceita
(`v4l2-ctl --list-formats-ext`). Sem ele o programa oferece uma lista genérica de
resoluções para escolher no escuro — e um nó `/dev/videoN` que só carrega
metadados aparece na lista como se fosse uma placa.

Outras distribuições: `sudo dnf install v4l-utils` (Fedora),
`sudo pacman -S v4l-utils` (Arch).

**2. Ambiente virtual e dependências.** No Ubuntu 24.04 e derivados (Zorin 18) o
`pip` recusa instalar no Python do sistema (PEP 668), então o venv não é
preferência — é o único caminho:

```bash
sudo apt install libasound2-plugins      # acesso ao PulseAudio/PipeWire
python3 -m venv ~/.venvs/captura_video
~/.venvs/captura_video/bin/pip install -r requisitos.txt
```

O venv fica **fora** da pasta do projeto de propósito: o repositório costuma
morar num disco externo NTFS/exFAT, que não suporta os links simbólicos que o
`venv` cria. Quem preferir outro lugar define `VENV_CAPTURA`. Um `.venv` dentro
da pasta do projeto, se existir, tem prioridade.

**3. Acesso a `/dev/video*`.** Em Ubuntu/Zorin modernos o `systemd-logind` já dá
acesso ao usuário da sessão gráfica por ACL, e nada precisa ser feito. Confira:

```bash
getfacl /dev/video0 | grep "^user:"
```

Aparecendo o seu usuário com `rw-`, está resolvido. Se não aparecer:

```bash
sudo usermod -aG video $USER      # exige sair e entrar na sessão de novo
```

**4. Abrir:**

```bash
chmod +x capturar.sh     # uma vez só
./capturar.sh
```

Para não depender do terminal, instale o atalho no menu de aplicativos — o
equivalente Linux do duplo clique no `.bat`:

```bash
./instalar_atalho.sh              # e depois procure por "Captura USB" no menu
./instalar_atalho.sh --remover    # para desfazer
```

O atalho aponta para esta pasta; movendo o repositório, rode de novo.

**Áudio.** A escolha do caminho é automática. Os wheels do PyAV **não** trazem o
demuxer `pulse`, então o programa alcança as fontes do PulseAudio/PipeWire pelo
plugin `pulse` do alsa-lib, abrindo `pulse:<fonte>` com o demuxer `alsa`. É por
aí que funcionam tanto o **áudio do computador** (a fonte «monitor» da saída em
uso) quanto o pareamento automático com a placa
([ADR-0023](adr/0023-pulseaudio-pelo-plugin-do-alsa.md)). O plugin vem no pacote
`libasound2-plugins`, que acompanha qualquer instalação de desktop; faltando
servidor de som, o programa cai para as placas ALSA cruas (`hw:N,0`), e aí o
áudio do computador não existe — ALSA não tem monitor de saída.

Em todos os casos o programa corrige antes a cópia do alsa-lib que vem dentro do
wheel do PyAV, que sobe sem configuração e faria toda gravação sair **muda, sem
erro nenhum** — e é essa mesma correção que torna o plugin `pulse` alcançável. É
automático; o porquê está em
[ADR-0020](adr/0020-reparar-o-alsa-embutido-no-pyav.md).

**Wayland.** Ecrã e janela não correm a mesma sorte aqui, e a diferença é
medida, não teórica. Confira em que sessão está:

```bash
echo $XDG_SESSION_TYPE      # "wayland" ou "x11"
```

| | Sessão Xorg | Sessão Wayland |
|---|---|---|
| **Placa de captura** | funciona | funciona |
| **Janela específica** | funciona | funciona, para aplicativos **XWayland** |
| **Ecrã inteiro** | funciona | **não é oferecido** |

O `x11grab` sobre a raiz da tela grava preto sob Wayland — o compositor não
mostra as janelas nativas ao servidor X. Em vez de oferecer uma opção que só
produz preto, o programa retira a captura de ecrã da lista e explica o motivo no
lugar dela. Para gravar o ecrã, escolha uma sessão **Xorg** na engrenagem da
tela de login.

Capturar uma **janela** continua funcionando sob Wayland, porque a janela de um
aplicativo XWayland é uma janela X de verdade e o `x11grab` a captura pelo
identificador. Aplicativos Wayland nativos não aparecem na lista — e não
aparecer é o comportamento certo, porque capturá-los por aqui daria preto.
Ver [ADR-0024](adr/0024-janela-por-window-id-e-wayland-pelo-tipo-de-sessao.md).

**Captura de janela específica** usa `xprop` e `xwininfo`, ambos do pacote
`x11-utils`, que já acompanha qualquer instalação gráfica. Se por algum motivo
faltarem:

```bash
sudo apt install x11-utils
```

---

## Linha de comando

De dentro da pasta do projeto:

```bash
python -m capturador             # abre a janela (o padrão)
python -m capturador --listar    # dispositivos e formatos, sem abrir a janela
python -m capturador --medir     # mede a taxa real de cada modo no terminal
python -m capturador --memoria   # o que ficou lembrado de cada aparelho
```

`--memoria` mostra o modo, o perfil e as medições guardados para cada placa, ecrã
e janela, junto com o caminho do banco. `--memoria --esquecer` apaga tudo e faz o
programa voltar ao palpite automático
([ADR-0025](adr/0025-memoria-de-escolhas-por-dispositivo.md)).

Opções de `--medir`:

| Opção | Efeito |
|---|---|
| `--segundos N` | duração de cada medição (padrão: 4) |
| `--tudo` | inclui também os formatos não comprimidos (bem mais lento) |

`--listar` é o primeiro comando a rodar quando algo não aparece: ele mostra o que
o sistema enxerga, sem a interface no meio.

---

## Primeira sessão

1. **Fonte** — escolha o tipo (placa, ecrã ou janela) e depois a fonte. Sendo
   placa, o áudio dela vem junto automaticamente
   ([ADR-0011](adr/0011-parear-video-e-audio-pelo-aparelho.md)).
2. **Testar equipamento** — opcional, mas vale a pena na primeira vez com uma
   placa nova: descobre o que ela e a máquina realmente aguentam, em vez do que
   está escrito na caixa ([ADR-0009](adr/0009-medir-em-vez-de-confiar.md)).
   Leva ~30 s e interrompe a prévia.
3. **Iniciar**.
4. **Gravar amostra** (10 s, com relatório do que ficou no arquivo) antes de
   valer, ou **Gravar** direto.

### Depois de gravar

O botão **Editar vídeos…**, no canto superior direito da janela, abre uma janela
separada para converter formato, cortar as pontas e juntar gravações num arquivo
só. Ela trabalha sobre arquivos já salvos e não interfere na captura.

Adicione os arquivos na ordem desejada e escolha uma linha da lista: ela aparece
na prévia ao lado. Arraste a barra até o ponto certo — os botões `−5s`/`−1s`/
`−1q` e as setas `←` `→` ajustam quadro a quadro — e fixe com **Marcar início**
(tecla `I`) e **Marcar fim** (tecla `O`). A faixa sob a barra mostra o que fica.
Sem marcas, o arquivo entra inteiro. Depois, **Salvar como…**.

A caixa **Recomprimir** é a decisão que importa:

- **Desmarcada** — copia os quadros como estão. Instantâneo, sem perda de
  qualidade, mesmo tamanho. O corte cai no quadro-chave mais próximo (o programa
  informa de quanto foi o desvio), e todos os arquivos precisam ter o mesmo
  codec e as mesmas dimensões.
- **Marcada** — recodifica. Demora, corta no quadro exato, encolhe muito o
  arquivo e junta origens diferentes uniformizando tudo.

Tentando juntar arquivos incompatíveis sem recomprimir, o programa recusa,
diz quais divergem e oferece recomprimir.
Ver [ADR-0026](adr/0026-pos-producao-copia-ou-recompressao.md).

| Atalho | Ação |
|---|---|
| `Ctrl+R` | inicia/para a gravação |
| `Ctrl+T` | testar equipamento |
| `F11` / duplo clique | tela cheia |
| `F12` | foto em resolução nativa |
| `Esc` | sai da tela cheia |

---

## Quando não funciona

| Sintoma | Sistema | Causa provável |
|---|---|---|
| Nenhuma placa na lista | Windows | `ffmpeg` fora do PATH, ou permissão de câmera desligada |
| Nenhuma placa na lista | Linux | sem acesso a `/dev/video*` — confira com `getfacl /dev/video0` |
| `externally-managed-environment` no `pip` | Linux | falta o venv: o PEP 668 bloqueia instalar no Python do sistema |
| Lista de formatos genérica, ou um `/dev/videoN` a mais | Linux | falta `v4l-utils` |
| **Gravação sai muda, sem erro nenhum** | Linux | alsa-lib do wheel do PyAV sem configuração — corrigido automaticamente ([ADR-0020](adr/0020-reparar-o-alsa-embutido-no-pyav.md)); reaparecendo, confira se `ALSA_CONFIG_PATH` está apontando para outro lugar |
| «Áudio do computador (indisponível)» | Linux | falta `libasound2-plugins`, ou o servidor de som não está no ar — o próprio programa diz qual, no botão «Como habilitar o áudio do computador» |
| Nenhum ecrã na lista | Linux | sessão Wayland — entre numa sessão Xorg ([ADR-0024](adr/0024-janela-por-window-id-e-wayland-pelo-tipo-de-sessao.md)) |
| Poucas janelas na lista | Linux | sessão Wayland: só aplicativos XWayland são capturáveis e listados |
| "Não foi possível abrir" / "dispositivo em uso" | ambos | a placa aceita **um** programa por vez: feche VLC, OBS, Discord, Teams, abas com câmera |
| Taxa de quadros abaixo do esperado | ambos | provavelmente a placa anunciando mais do que entrega — rode *Testar equipamento* |
| Tela preta com a placa selecionada | ambos | sem sinal na entrada HDMI, ou conteúdo com HDCP (Netflix, Blu-ray, console) — que nenhum hardware captura |

Diagnóstico detalhado, com comandos para os dois sistemas, em
[COMO_ENCONTRAR_A_PLACA.md](../COMO_ENCONTRAR_A_PLACA.md).
