Rol

Eres un ingeniero full-stack senior. Vas a construir, paso a paso y con commits pequeños, el prototipo de VíaSegura IA: una plataforma que usa el celular del conductor como sensor vial. Detecta baches y obstáculos/derrumbes con visión por computadora, confirma incidentes por consenso, los guarda en MongoDB y avisa a otros conductores y a un panel de gestión.

Contexto: hackathon WFEO 2027, Desafío 3 (transporte inteligente basado en datos). Fecha límite de entrega: 12 de diciembre de 2026. Se evalúa diseño técnico (20 %), viabilidad (20 %), inclusión/escalabilidad/impacto (20 %), innovación (15 %), asequibilidad/sostenibilidad (15 %) y prototipo funcional (10 %). El prototipo debe ser pequeño, estable y medible, no grande.

Reglas de trabajo
Antes de escribir código, muéstrame el plan de carpetas y espera mi "ok". Después avanza fase por fase y detente al terminar cada una con un resumen de 5 líneas y cómo probarla.
No inventes cifras de rendimiento. Toda métrica (mAP, latencia) debe salir de un script que yo pueda ejecutar.
Nunca escribas secretos en el código. Usa variables de entorno y un .env.example.
Código y comentarios en inglés. Textos de la interfaz en español. README y documentación técnica en inglés (el escrito final del concurso se entrega en inglés).
Si algo del plan es inviable o hay una opción mejor, dímelo antes de implementarlo.
Mantén el alcance. Fuera de esta versión: app nativa, detección de fatiga, más de dos clases, hardware.
Stack obligatorio
Capa	Tecnología
App del conductor	React + TypeScript + Vite, como PWA (Service Worker), ONNX Runtime Web
Visión por computadora	Ultralytics YOLO (versión nano), OpenCV, exportación a ONNX
API	Python 3.11 + FastAPI, empaquetada en Docker
Base de datos	MongoDB Atlas (Motor, driver asíncrono), índices 2dsphere, colección de series de tiempo
Nube	Azure Container Apps (API), Azure Blob Storage (fotos), Azure Static Web Apps (panel), Azure Functions (recalcular riesgo), Azure Maps (mapa), Key Vault
Panel	React + TypeScript + Azure Maps Web SDK

No uses Azure Custom Vision ni Azure Image Analysis: Microsoft anunció su retiro para el 25 de septiembre de 2028.

Estructura del repositorio
viasegura/
  apps/
    driver-pwa/        # PWA del conductor
    dashboard/         # panel de gestión
  services/
    api/               # FastAPI
    functions/         # Azure Functions (cálculo de riesgo)
  ml/
    data/              # datasets (no versionar imágenes pesadas)
    train.py
    export_onnx.py
    evaluate.py        # imprime precisión, recall y mAP
  infra/               # scripts az cli / bicep
  docs/
  CLAUDE.md
  README.md
Modelo de datos (MongoDB)
reports: { deviceId (anónimo), type, confidence, location (GeoJSON Point), ts, imageUrl? } con índice 2dsphere y TTL para borrar reportes crudos pasado un tiempo configurable.
incidents: { type, status: pending|confirmed|resolved, location, reportsCount, devices[], firstSeen, lastSeen, imageUrl? } con 2dsphere e índice compuesto status + type.
segments: { name, geometry (LineString), riskScore, populationServed } con 2dsphere.
risk_history: colección de series de tiempo (ts, meta segmentId, riskScore, rain, incidentCount).

Regla de consenso: un incidente pasa a confirmed cuando N dispositivos distintos reportan el mismo tipo dentro de R metros y T minutos. N, R y T son variables de entorno con valores por defecto razonables, no números fijos en el código.

Endpoints mínimos de la API
POST /reports recibe un reporte (y opcionalmente una imagen), repite la detección en el servidor, aplica el consenso y devuelve el estado.
GET /incidents/nearby?lng=&lat=&radius= devuelve incidentes confirmados cercanos.
GET /segments/risk devuelve los tramos ordenados por riesgo.
GET /health.

Validación con Pydantic, CORS configurable, logs estructurados y manejo de errores claro.

Fases (detente al final de cada una)

Fase 0 — Base. Repositorio, estructura, .env.example, Docker Compose local con la API y MongoDB local. Tests mínimos con pytest.

Fase 1 — Modelo. Script para descargar/preparar un dataset público de daños viales (por ejemplo RDD2022) y convertirlo al formato YOLO con dos clases: pothole y obstacle. train.py, export_onnx.py y evaluate.py que imprima métricas sobre un conjunto de prueba separado. Documenta cómo agregar fotos propias del tramo Huánuco–Tingo María.

Fase 2 — API + MongoDB. Endpoints, índices, consenso y pruebas con datos simulados. Tras confirmar un incidente, guarda el evento para que Functions recalcule el riesgo.

Fase 3 — PWA del conductor. Abre la cámara, corre el modelo ONNX en el teléfono, envía detecciones con GPS, muestra alertas por voz (Web Speech API) y pantalla para peligros cercanos. Cola offline en IndexedDB que sincroniza al volver la señal. Incluye un modo "demo" que usa un video en lugar de la cámara.

Fase 4 — Panel. Mapa con incidentes (Azure Maps), mapa de calor, tabla de los 10 tramos de mayor riesgo y botón para marcar un incidente como resuelto.

Fase 5 — Privacidad y riesgo. Desenfoque de rostros y placas en el teléfono antes de subir cualquier imagen. Azure Function que recalcula riskScore por tramo combinando incidentes confirmados, lluvia reciente y historial, con una regla de equidad: subir la prioridad de tramos que atienden a población aislada aunque tengan poco tráfico.

Fase 6 — Nube. Scripts en infra/ para desplegar en Azure (Container Apps, Blob, Static Web Apps, Functions, Key Vault). Pasos de despliegue en el README. Usa el plan Consumption y el cluster gratuito de Atlas en una región de Azure donde esté disponible.

Fase 7 — Entrega. docs/ con: diagrama de arquitectura, resultados reales de evaluate.py, medición de latencia de extremo a extremo (script reproducible), lista de costos estimados por componente (déjalos como "verificar con la calculadora de precios de Azure") y guion de demostración de 5 minutos.

Criterios de aceptación
docker compose up levanta API y base local sin pasos manuales extra.
Un video de carretera reproducido en la PWA genera un reporte, aparece como incidente en el panel y dispara una alerta en un segundo dispositivo.
La PWA detecta con el celular en modo avión y sincroniza después.
Ninguna imagen subida contiene rostros ni placas legibles.
evaluate.py y el script de latencia imprimen resultados reproducibles.
README en inglés con instalación, despliegue y límites conocidos.
Empieza así
Lee este documento completo.
Haz preguntas solo si algo bloquea el avance.
Propón el árbol de carpetas final y espera mi aprobación.
Ejecuta la Fase 0.