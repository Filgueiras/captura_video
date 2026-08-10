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
| **Áudio** | DirectShow, junto com o vídeo | PulseAudio/PipeWire ou ALSA, escolhido em tempo de execução |
| **Captura de ecrã** | `ddagrab` (Desktop Duplication) — 41 fps aqui | só em sessão **Xorg**; sob Wayland grava preto |
| **Captura de janela** | `gdigrab` | `wmctrl` + `xdotool`, e também só em Xorg |
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
  (`x11grab`) e o substituto exige um protocolo inteiro
  (`xdg-desktop-portal` + PipeWire) ainda não implementado aqui.

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

**Áudio.** A escolha entre PulseAudio/PipeWire e ALSA é automática e leva em
conta o que o FFmpeg embutido no PyAV realmente suporta — nem todo wheel do PyAV
é compilado com `libpulse`, então não basta o `pactl` existir no sistema.

Quando cai para ALSA, o programa também corrige a cópia do alsa-lib que vem
dentro do wheel, que sobe sem configuração e faria toda gravação sair **muda, sem
erro nenhum**. É automático; o porquê está em
[ADR-0020](adr/0020-reparar-o-alsa-embutido-no-pyav.md).

**Wayland.** A captura de **ecrã** e de **janela** usa `x11grab`, que sob Wayland
grava **tela preta** — o compositor não expõe as janelas nativas ao XWayland.
Isso vale para GNOME (Zorin, Ubuntu), KDE e Sway. Confira em que sessão está:

```bash
echo $XDG_SESSION_TYPE      # "wayland" ou "x11"
```

Captura de **placa** funciona normalmente nos dois casos — é só a captura de tela
que depende disso. Para gravar a tela, escolha uma sessão **Xorg** na engrenagem
da tela de login.

> **Limitação conhecida.** O programa hoje ainda *oferece* as opções de ecrã e
> janela sob Wayland, e elas gravam preto. A detecção erra porque testa a
> ausência de `DISPLAY`, e o XWayland mantém essa variável definida. A correção
> própria seria capturar via `xdg-desktop-portal` + PipeWire, que é o caminho
> nativo do Wayland.

**Captura de janela específica** no Linux precisa de `wmctrl` e `xdotool` (e,
como acima, de uma sessão Xorg):

```bash
sudo apt install wmctrl xdotool
```

---

## Linha de comando

De dentro da pasta do projeto:

```bash
python -m capturador             # abre a janela (o padrão)
python -m capturador --listar    # dispositivos e formatos, sem abrir a janela
python -m capturador --medir     # mede a taxa real de cada modo no terminal
```

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
| Ecrã/janela gravam preto | Linux | sessão Wayland — entre numa sessão Xorg |
| "Não foi possível abrir" / "dispositivo em uso" | ambos | a placa aceita **um** programa por vez: feche VLC, OBS, Discord, Teams, abas com câmera |
| Taxa de quadros abaixo do esperado | ambos | provavelmente a placa anunciando mais do que entrega — rode *Testar equipamento* |
| Tela preta com a placa selecionada | ambos | sem sinal na entrada HDMI, ou conteúdo com HDCP (Netflix, Blu-ray, console) — que nenhum hardware captura |

Diagnóstico detalhado, com comandos para os dois sistemas, em
[COMO_ENCONTRAR_A_PLACA.md](../COMO_ENCONTRAR_A_PLACA.md).
