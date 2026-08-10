# ADR-0017 — Preferências do usuário em `QSettings`

**Estado:** Aceito
**Data:** 2026-07-26

## Contexto

Um punhado de escolhas precisa sobreviver ao fechamento do programa: tema, tipo
de fonte, pasta de destino, perfil de gravação, fator de qualidade, volume,
mostrar cursor, vincular áudio, monitorar áudio, escolher destino ao gravar.

São dez chaves de tipos simples. Nenhuma delas é estrutura, nenhuma precisa ser
editada à mão, nenhuma precisa viajar entre máquinas.

## Decisão

`QSettings("capturador", "CapturaUSB")`, gravando **na hora da mudança** — cada
`toggled`/`valueChanged` chama `setValue` no próprio slot — e não num "salvar
configurações" no fechamento.

```python
self.config = QSettings("capturador", "CapturaUSB")
self._modo_tema = self.config.value("tema", tema.AUTO)
```

Onde isso vai parar depende do sistema, e é responsabilidade do Qt: registro do
Windows em `HKCU\Software\capturador\CapturaUSB`, ou
`~/.config/capturador/CapturaUSB.conf` no Linux.

## Consequências

- Zero código de serialização, zero decisão sobre onde guardar arquivo de
  configuração em cada sistema.
- Um travamento não perde as preferências: elas já estão gravadas.
- `QSettings` devolve **string** para tudo no Windows. Booleanos exigem
  `type=bool` explícito (`self.config.value("cursor", True, type=bool)`) e
  números exigem conversão (`int(self.config.value("qualidade", 20))`).
  Esquecer isso produz um bug silencioso — a string `"false"` é verdadeira em
  Python.
- Escrever a cada mudança significa muitas escritas pequenas. Irrelevante: são
  eventos de interface humana, não um laço.
- O fator de qualidade é a exceção, salvo no `closeEvent`: `QSpinBox` emite
  `valueChanged` a cada tecla digitada, e gravar em cada dígito não acrescenta
  nada.
- Não há como o usuário editar as preferências fora do programa no Windows, nem
  levá-las para outra máquina. Para dez chaves, ninguém quer.
- O que **não** é persistido é tão deliberado quanto o que é: o dispositivo e o
  modo escolhidos. Eles dependem do hardware presente naquele momento, e
  restaurar uma placa que não está mais conectada geraria um erro na abertura em
  vez de conveniência.

## Alternativas consideradas

**Arquivo JSON ao lado do executável.** Legível e editável, e quebra em
instalação por usuário sem permissão de escrita em `Program Files` — que é
exatamente onde um executável empacotado
([0018](0018-empacotar-com-pyinstaller-em-modo-pasta.md)) costuma parar.

**TOML/INI em `~/.config` escrito à mão.** Reimplementa `QSettings` com pior
suporte a plataforma, para ganhar uma edição manual que ninguém pediu.

**Não persistir nada.** Reconfigurar tema, pasta e perfil a cada abertura é
atrito puro, todo dia.
