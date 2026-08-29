# Casos de Uso — BARF

Todos los casos de uso asumen: propiedades propias o con permiso, volúmenes bajos/razonables, y respeto a robots.txt y ToS.

## 1. Pruebas de accesibilidad

- **Auditoría del reproductor**: comprobar que el reproductor de vídeo (YouTube u otro) es operable por teclado, tiene etiquetas ARIA correctas, contraste suficiente y subtítulos accesibles.
- **Navegación con lectores de pantalla**: simular flujos (buscar, reproducir, pausar) y verificar que los elementos críticos son anunciados correctamente.
- **Usuarios con discapacidad motora**: validar que no hay zonas de clic demasiado pequeñas y que el foco es visible.

## 2. Investigación de UX

- **Patrones de navegación**: estudiar cómo varía el scroll, el orden de lectura y los tiempos de permanencia según el diseño de la interfaz (en sitios propios o de prueba).
- **Velocidades de conexión**: simular conexiones lentas (throttling) para medir impacto en la experiencia y detectar problemas de rendimiento percibido.
- **Pruebas A/B de flujos**: comparar versiones de un formulario o checkout en entornos de desarrollo.

## 3. Educación en automatización

- **Talleres de Playwright**: ejemplos comentados de selectores, esperas, fixtures y paralelismo.
- **Estudio de anti-bots**: usar `playwright-stealth` en un laboratorio local para *observar* qué señales detectan los sistemas anti-bot (webdriver, fingerprints, patrones de red). Objetivo: entender y defender, no saltar protecciones.
- **MCP para agentes de IA**: aprender a exponer herramientas de navegador como herramientas MCP y cómo un agente las invoca.

## 4. Herramienta de desarrollo

- **Tests de humo**: verificar que una app web carga, navega y responde tras un despliegue, sin depender de la API.
- **Captura de regresiones**: screenshots comparativos de páginas clave.
- **Monitorización ligera**: comprobar disponibilidad de flujos críticos propios (login, búsqueda) con alertas.

## 5. Estudio de redes y geolocalización (sandbox)

- **Cómo cambia el contenido según región**: observar (a bajo volumen, en entorno controlado) cómo responde un sitio público a diferentes IPs/geos — con proxies de prueba o listas públicas, **nunca** para ocultar actividad.
- **Enrutamiento y latencia**: medir tiempos de respuesta según salida.

---

## Lo que BARF no hace (ni en los ejemplos)

- No reproduce vídeos para inflar watch time ni views
- No da likes, suscripciones ni comentarios automáticos
- No rota identidades para burlar rate limits de producción
- No escala más allá de lo razonable para investigación
