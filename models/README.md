# Modelos de mãos e rosto

Os arquivos `.task` são baixados por **Instalar ou reparar.cmd** e ficam fora do versionamento.

## Mãos

- Fonte: [modelo oficial do Google — Hand Landmarker, float16, versão 1](https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task).
- SHA256 esperado: `fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1`.
- O instalador e o aplicativo verificam a integridade do arquivo antes de usá-lo.

Documentação: [MediaPipe Hand Landmarker](https://ai.google.dev/edge/mediapipe/solutions/vision/hand_landmarker/python).

## Rosto e expressões para zoom

- Arquivo: `face_landmarker.task`.
- Fonte: [modelo oficial do Google — Face Landmarker, float16, versão 1](https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task).
- SHA256 esperado: `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff`.
- O instalador e o aplicativo conferem a integridade antes do uso.
- O aplicativo usa os sinais de fechamento dos olhos e das sobrancelhas; as imagens não são gravadas.

Documentação: [MediaPipe Face Landmarker para Python](https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker/python).
