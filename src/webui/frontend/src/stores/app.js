import { defineStore } from 'pinia';

/** Shell store; feature stores split off during Phase D migration. */
export const useAppStore = defineStore('app', {
  state: () => ({
    /** Reserved for shell / global UI flags */
    ready: true,
  }),
});
