// Registro del tab "Youber" en la Control UI (Fase 2).
//
// El descriptor se anuncia a los clientes de la Control UI en el hello de la
// Gateway (controlUiTabs); el tab aparece solo con el plugin habilitado. El
// contenido se sirve desde la ruta HTTP /youber-dashboard (auth "plugin"),
// que la UI renderiza en un iframe con sandbox (sin token).

export function registerTab(api) {
  api.session.controls.registerControlUiDescriptor({
    surface: "tab",
    id: "youber",
    label: "Youber",
    description: "Panel de control de Youber",
    icon: "dashboard",
    group: "control",
    order: 60,
    requiredScopes: ["operator.read"],
    path: "/youber-dashboard",
  });
}
