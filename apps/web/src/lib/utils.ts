import { createCn } from 'cn/config';

// Custom @theme text sizes must not be merged as text colors.
export const cn = createCn({
  extend: { classGroups: { 'font-size': [{ text: ['caption', 'agent'] }] } },
});
