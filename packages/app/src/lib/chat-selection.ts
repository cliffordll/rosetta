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
  upstreams: ReadonlyArray<{ id: string; enabled: boolean }>,
  emptyChoice: string,
): string {
  return upstreams.find((upstream) => upstream.enabled)?.id ?? emptyChoice;
}
