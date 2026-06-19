export interface ChatSelection<TServerApi extends string> {
  serverApi: TServerApi;
  upstreamChoice: string;
  model: string;
}

export function changeServerApiSelection<TServerApi extends string>(
  current: ChatSelection<TServerApi>,
  serverApi: TServerApi,
): ChatSelection<TServerApi> {
  return { ...current, serverApi, model: "" };
}

export function initialUpstreamChoice(
  upstreams: ReadonlyArray<{ id: string; enabled: boolean; is_default: boolean }>,
  emptyChoice: string,
): string {
  const globalDefault = upstreams.find((upstream) => upstream.enabled && upstream.is_default);
  return globalDefault?.id ?? upstreams.find((upstream) => upstream.enabled)?.id ?? emptyChoice;
}

export function ensureUpstreamChoice(
  currentChoice: string,
  upstreams: ReadonlyArray<{ id: string; enabled: boolean; is_default: boolean }>,
  emptyChoice: string,
): string {
  return currentChoice === emptyChoice
    ? initialUpstreamChoice(upstreams, emptyChoice)
    : currentChoice;
}
