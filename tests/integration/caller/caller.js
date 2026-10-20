// `/<binding>/<path>` is forwarded to Steward's HubApi through that binding, keeping the
// method, headers, body and query string, so the tests decide everything HubApi sees.
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const [, name, ...rest] = url.pathname.split("/");
    const binding = { "with-props": env.WITH_PROPS, "no-props": env.NO_PROPS }[name];
    if (binding === undefined) {
      return new Response("unknown binding", { status: 404 });
    }
    return binding.fetch(new Request(`https://steward/${rest.join("/")}${url.search}`, request));
  },
};
