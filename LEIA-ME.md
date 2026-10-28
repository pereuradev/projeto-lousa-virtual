# Projeto Lousa Virtual

Aplicativo Python para Windows: desenhe no ar usando uma webcam ou desenhe com o mouse. A interface concentra as ferramentas em uma única barra, com a câmera na lateral e Ajuda acessível pelo botão no topo ou pela tecla F1.

## Abrir e usar

1. Na primeira execução, instale [uv](https://docs.astral.sh/uv/getting-started/installation/) e execute **Instalar ou reparar.cmd**. Depois, dê dois cliques em **Iniciar Lousa.cmd**.
2. A câmera 0 abre automaticamente. Aguarde o detector iniciar.
3. Mostre uma mão inteira, com boa iluminação. O indicador move o cursor na lousa.
4. Junte as pontas do polegar e indicador para desenhar. Separe-as para parar o traço.
5. Clique em **Salvar PNG** ou pressione **S**. O desenho vai para a pasta **desenhos**, dentro do projeto.

## Cores: ative com joinha e depois conte os dedos

O aplicativo inicia em **modo Desenho**: a contagem de dedos fica desligada e a pinça desenha normalmente.

1. Mostre **um joinha**: somente o polegar estendido e os outros quatro dedos dobrados, durante **1 segundo contínuo**.
2. Aguarde o aviso **Cores ativadas** e **solte o joinha**. Manter o gesto de ativação não escolhe Preto.
3. Mostre exatamente **uma mão inteira** e mantenha o número de dedos desejado por **5 segundos contínuos**, em qualquer lugar da imagem.
4. Ao selecionar a cor, o aplicativo **volta automaticamente ao modo Desenho**. Para trocar novamente pela câmera, faça outro joinha.

O título indica o modo atual e a barra mostra a permanência reconhecida. A posição da mão não escolhe a cor.

| Dedos estendidos de uma mão | Cor após 5 segundos |
|---|---|
| 1 | Preto |
| 2 | Azul |
| 3 | Vermelho |
| 4 | Verde |
| 5 | Roxo |

No modo Cores, o polegar também conta quando está estendido. Deixe os demais dedos bem dobrados e a mão inteira visível. Mudar a quantidade de dedos reinicia os cinco segundos, sem somar períodos separados. A pinça cancela a escolha e volta ao desenho. Perder a mão, pausar ou interromper o rastreamento também cancela o modo Cores; faça outro joinha para reativar. Fora do modo Cores, mostrar 1–5 dedos não troca a cor nem bloqueia a preparação da pinça. A cor ativa é indicada pelo nome ao lado de Lousa e pelo contorno do círculo selecionado. A troca de cor encerra o traço anterior.

## Limpar: DUAS mãos abertas por DOIS segundos

Mostre **as duas palmas abertas**, cada uma com **cinco dedos estendidos**, por **2 segundos contínuos**. A barra vermelha mostra o progresso. Fechar ou retirar qualquer mão antes de completar cancela a limpeza. **Uma mão aberta não apaga a lousa; no modo Cores, cinco dedos escolhem Roxo após 5 segundos.**

Depois de limpar, **Z / Desfazer recupera o desenho**. Manter as duas mãos abertas não repete a limpeza. Para limpar novamente, feche ao menos uma mão de forma visível; há um intervalo de segurança de 3 segundos após a limpeza, seguido de outra permanência de 2 segundos.

Com **duas mãos em qualquer outra pose**, o aplicativo suspende desenho e escolha de cor. Os dedos das duas mãos nunca são somados para selecionar uma cor. Mostre só uma mão para voltar a desenhar ou escolher cor. Durante a limpeza, nenhuma cor é selecionada e nenhum traço é criado.

Todos os gestos de controle ficam suspensos em pausas, janelas de confirmação e desenho com mouse. Os botões de cor continuam clicáveis, e as teclas 1–5 continuam funcionando.

## Controles

| Ação | Controle |
|---|---|
| Cores: preto, azul, vermelho, verde, roxo | Joinha por 1 s, solte, depois 1–5 dedos por 5 s; botões ou teclas 1–5 |
| Caneta / borracha | E alterna; B volta à caneta |
| Espessura da caneta: 2 a 40 pixels | Controle Traço ou + / - |
| Borracha | Usa 3 vezes a espessura selecionada |
| Desfazer até 25 ações | Z ou Ctrl+Z |
| Limpar | C, com confirmação; Z pode desfazer |
| Limpar pela câmera | DUAS palmas abertas por 2 s; feche uma antes para cancelar; Z desfaz |
| Salvar desenho em PNG | S; nomes únicos, sem sobrescrever |
| Pausar / retomar gestos | Espaço; mouse continua funcionando |
| Ajuda e atalhos | Botão Ajuda ou F1; os gestos são suspensos enquanto a janela estiver aberta |
| Fechar | X ou Esc; oferece salvar alterações |
| Trocar câmera | Desconectar, escolher número 0–9 e Conectar |

A prévia é espelhada. O cursor usa a região central da câmera para facilitar alcançar as bordas da lousa. O movimento do indicador alcança toda a área branca da lousa. A pinça tem histerese e confirmação em dois quadros; o cursor tem suavização. Ao perder a mão, o traço para. O PNG tem 1280 × 800 pixels e fundo branco, sem câmera, paleta, cursor ou botões.

## Privacidade

Este aplicativo processa frames na memória do computador. Não faz upload de imagens, não grava vídeo e não usa microfone. Somente o desenho é exportado quando você solicita. A câmera é liberada ao desconectar ou fechar. Internet é usada na instalação ou reparo para baixar bibliotecas e o modelo.

A documentação da biblioteca MediaPipe informa processamento local das imagens e coleta de métricas de desempenho/utilização; por isso, não se promete ausência absoluta de comunicação de rede da biblioteca. Consulte o [aviso oficial](https://pypi.org/project/mediapipe/). Nenhum serviço online é usado pelo código do aplicativo durante o desenho.

## Se a câmera não abrir

- Feche Teams, Zoom e outras páginas ou aplicativos que estejam usando a câmera.
- Confira o cabo USB e a tampa física da webcam.
- Confira a permissão de câmera para aplicativos da área de trabalho nas Configurações do Windows.
- Teste outro número de câmera. A mudança só é aplicada após desconectar e conectar.
- Enquanto isso, use o mouse. Não é necessário reiniciar a lousa.

Falhas de inicialização são registradas em **erro.log**, sem imagens. Falhas da câmera aparecem no rodapé. Se houver erro de DLL do OpenCV, confira o [Visual C++ Redistributable x64 da Microsoft](https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist). Edições Windows N podem exigir o Media Feature Pack. O aplicativo não altera permissões do Windows por conta própria.

## Instalação e desenvolvimento

Ambiente validado: Python **3.12.13 x64**, MediaPipe **1.1.1**, OpenCV contrib **4.14.0.94**, Pillow **12.2.0**. O Python fica em `.python` e as bibliotecas em `.venv`, dentro deste projeto. O instalador obtém esse Python dentro do projeto; não é necessária uma instalação global de Python.

Na instalação de um clone ou ZIP, execute **Instalar ou reparar.cmd** antes do iniciador. Esse script sincroniza as versões de `requirements.lock.txt` e confere o SHA256 do modelo. Requer internet e [uv](https://docs.astral.sh/uv/getting-started/installation/) disponível no computador. Não apaga desenhos. Preserve o caminho da pasta; ambientes virtuais não são portáteis. Se mover o projeto, remova somente a pasta `.venv` gerada anteriormente e execute o instalador novamente para recriar o ambiente no novo caminho. Preserve a pasta `desenhos`.

Comandos no PowerShell, dentro desta pasta:

```powershell
& '.\.venv\Scripts\python.exe' main.py
& '.\.venv\Scripts\python.exe' main.py --camera 1
& '.\.venv\Scripts\python.exe' main.py --no-camera
& '.\.venv\Scripts\python.exe' main.py --diagnose
& '.\.venv\Scripts\python.exe' -m unittest discover -s tests -v
```

O diagnóstico abre a webcam brevemente, executa inferência e imprime apenas contagens e erros; não salva imagens. Reconhecer uma mão no diagnóstico não equivale a validar um gesto de pinça de uma pessoa.

## Estrutura e fontes

- `main.py`: entrada e tratamento de erros.
- `lousa/app.py`: interface Tkinter e atalhos.
- `lousa/camera.py`: captura OpenCV e detector em thread separada.
- `lousa/drawing.py`: desenho, histórico, PNG e filtro de gestos.
- `lousa/controls.py`: contagem de dedos por 5 s e limpeza com duas mãos por 2 s.
- `models/hand_landmarker.task`: modelo oficial, float16, versão 1, baixado pelo instalador e não versionado.
- `tests/`: verificações automatizadas sem webcam.
- `VALIDACAO.md`: resultados verificados nesta entrega.

Fontes primárias: [MediaPipe Hand Landmarker para Python](https://ai.google.dev/edge/mediapipe/solutions/vision/hand_landmarker/python), [instalação MediaPipe](https://ai.google.dev/edge/mediapipe/solutions/setup_python), [OpenCV contrib](https://pypi.org/project/opencv-contrib-python/), [modelo Google versão 1](https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task).

SHA256 do modelo: `fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1`.

Limitações: até duas mãos rastreadas, desenho e escolha de cor com exatamente uma mão, desenho em 2D; oclusão, pouca luz e movimentos rápidos reduzem a precisão. A distância ideal e os limiares podem variar com a webcam. Não inclui reconhecimento de texto nem colaboração online.
