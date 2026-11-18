import { UserManager, WebStorageStateStore } from "oidc-client-ts";

const authority = import.meta.env.VITE_OIDC_ISSUER;
const clientId = import.meta.env.VITE_OIDC_CLIENT_ID;
export const oidc =
  authority && clientId
    ? new UserManager({
        authority,
        client_id: clientId,
        redirect_uri: location.origin + "/identity",
        response_type: "code",
        scope: "openid phone",
        automaticSilentRenew: false,
        userStore: new WebStorageStateStore({ store: sessionStorage }),
      })
    : null;

export async function providerToken(): Promise<string> {
  const user = await oidc?.getUser();
  if (!user?.id_token || user.expired)
    throw new Error("Sign in with the configured identity provider.");
  return user.id_token;
}
