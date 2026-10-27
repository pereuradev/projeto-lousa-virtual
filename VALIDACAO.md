# Validação — zoom por olhos e sobrancelhas

Atualização do Projeto Lousa Virtual em 27/10/2026.

## Comportamento

- O olho esquerdo da pessoa fechado continuamente por 2 segundos, com o direito aberto, ativa o modo Zoom.
- Após abrir os dois olhos e relaxar as sobrancelhas, levantá-las amplia e franzir/abaixar reduz. Relaxar interrompe o ajuste.
- O olho direito fechado continuamente por 2 segundos, com o esquerdo aberto, confirma a visualização.
- O zoom é centralizado, entre 50% e 300%, com controles manuais e restauração para 100%.
- Durante o ajuste facial, as mãos não desenham, não escolhem cores e não limpam. Uma soltura visível da pinça é exigida antes de retomar o desenho.
- Perda de rosto, pausa, Ajuda e reconexão interrompem a sessão e seus temporizadores. O zoom atual permanece.
- A imagem de rosto usada na inferência não é espelhada, preservando os lados da pessoa. A prévia e o rastreamento de mãos mantêm o espelhamento.
- Falha no modelo facial não impede o uso com mãos ou mouse.
- Zoom altera somente a visualização: desenho, histórico, espessura em pixels e PNG integral de 1280 × 800 permanecem independentes da ampliação.

## Gestos anteriores preservados

- O aplicativo inicia em modo Desenho. Mostrar 1–5 dedos não seleciona cores nem bloqueia a preparação da pinça.
- Um joinha (somente o polegar estendido e os outros quatro dedos dobrados) por 1 segundo contínuo ativa o modo Cores.
- É necessário soltar o joinha antes de iniciar a contagem. Segurar a ativação não escolhe Preto.
- No modo Cores, exatamente uma mão com a mesma contagem por 5 segundos seleciona 1 Preto, 2 Azul, 3 Vermelho, 4 Verde ou 5 Roxo.
- Escolher a cor retorna automaticamente ao desenho. Outra troca por câmera exige novo joinha.
- Pinça cancela a escolha e libera desenho; perda de mão, pausa, interrupção de rastreamento e duas mãos também cancelam o modo Cores.
- Duas palmas abertas mantêm a limpeza por 2 segundos, com cancelamento, Desfazer, soltura obrigatória e intervalo de segurança de 3 segundos.
- A interface indica Desenho, Ativando cores e Cores ativadas, além do progresso. A paleta clicável, os atalhos e os demais recursos continuam disponíveis.

## Verificações

O modelo facial oficial, float16 versão 1, foi baixado do Google e teve seu SHA256 conferido. Os dois modelos reais foram carregados, executados sobre uma imagem preta em memória e fechados corretamente, sem câmera ou arquivos de imagem.

Os testes automatizados exercitam temporizadores e transições faciais com sinais sintéticos, transformações de coordenadas, preservação do desenho e comunicação entre câmera e interface. A suíte inclui os testes anteriores de pinça, cores por joinha, limpeza, histórico e PNG.

**148 testes passaram, sem testes ignorados**, no Windows com os widgets Tk reais. São 81 verificações anteriores preservadas, 30 do controlador facial, 9 da geometria de zoom, 11 do transporte e segurança, 8 da interface e 9 da integração da câmera. A suíte também passou na instalação da área de trabalho.

Os testes do worker executam o fluxo completo com observações sintéticas, incluindo ativação, ajuste, confirmação, perda de mão, soltura obrigatória e novo traço. Verificam também rosto sem espelhamento, falha facial preservando os recursos das mãos, encerramento dos detectores e rejeição de comandos antigos de cor, limpeza e zoom.

A interface foi conferida com widgets reais em 1000 × 640 e 1180 × 780 e em janela ampla. A captura visual de 1000 × 640 confirmou os controles de zoom, estado facial e instruções sem cortes. Foram conferidos os botões de ampliar e restaurar a visão, além da Ajuda com o fluxo facial. As revisões independentes de especificação e qualidade terminaram sem achados pendentes.

A validação foi realizada em um ambiente local Windows com as dependências fixadas neste repositório. Não houve gravação ou exportação de imagens da câmera.

## Limitação

Não houve validação dos novos gestos faciais com uma pessoa diante da webcam. Os limiares de olhos e sobrancelhas são iniciais; óculos, iluminação, posição, oclusões e diferenças entre expressões podem exigir ajuste. Testes sintéticos e carregamento do modelo não demonstram reconhecimento confiável de gestos reais de uma pessoa.

O aplicativo não grava frames de câmera nem cria cadastro ou identificação de rostos. Desenhos pessoais e modelos binários ficam fora do versionamento.
