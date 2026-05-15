# Sistema de Plugins para RecetaDolce

RecetaDolce utiliza una arquitectura modular basada en Next.js App Router. Puedes añadir "plugins" o nuevas funcionalidades siguiendo estas guías:

## 1. Añadir Scripts Externos (Marketing, Tracking, Widgets)
No necesitas tocar el código para scripts básicos. Ve al **Panel de Administración > Ajustes > Código** e inserta tus scripts en:
- **Header Code**: Para Google Search Console, Pinterest Verify, Meta Tags.
- **Footer Code**: Para widgets de chat (Tawk.to, WhatsApp), scripts de analíticas secundarias.

## 2. Crear Nuevos "Power-Ups" en el Panel
Si quieres añadir herramientas de gestión (como un generador de PDFs o un optimizador de imágenes):
1. Crea la lógica en `app/api/admin/tu-herramienta/route.ts`.
2. Añade la interfaz en `app/admin/settings/page.tsx` dentro de una nueva pestaña.
3. Registra el componente en la barra lateral de ajustes.

## 3. Webhooks y Automatización (AuraSEO Nexus)
RecetaDolce está diseñado para recibir contenido de **AuraSEO Nexus**. Puedes extender esta integración:
- Modifica `app/api/publish/route.ts` para disparar acciones después de publicar (ej: enviar a Telegram, publicar en Pinterest).
- Usa la `CMS_API_KEY` para asegurar tus endpoints.

## 4. Plugins de UI (Componentes)
Para añadir nuevos elementos visuales:
1. Crea tu componente en `components/`.
2. Importalo en `app/[slug]/page.tsx` o `app/layout.tsx`.
3. Usa Tailwind CSS para mantener la estética premium.

---
*Para soporte técnico sobre el sistema de plugins, consulta la documentación de AuraSEO Nexus.*
# Nota actual - 2026-05-10

La administracion de suscriptores no es un plugin de interfaz. Debe hacerse desde la CLI raiz con `python rankstein.py subscribers ...`. No expongas claves de Supabase, credenciales de Gemini, credenciales de Pinterest ni rutas de sesiones de navegador en componentes cliente.

---
