import { Link } from '@tanstack/react-router';
import { ArrowLeft } from 'lucide-react';
import { PublicLayout, siteWidth, usePageTitle } from './public-layout';

const content = {
  privacy: {
    title: 'Privacy',
    intro: 'How information is used in an Openlet workspace.',
    sections: [
      [
        'Account and workspace information',
        'Openlet uses Clerk for authentication. Your account identifies the workspaces, agents and storage you can access. Workspace membership and permissions determine access to conversations and files.',
      ],
      [
        'Conversations and files',
        'Messages, file references and uploaded files are stored so you and your agents can continue working. Workspace owners with the relevant permissions can follow agent activity. Your workspace administrator controls membership and access.',
      ],
      [
        'AI providers',
        'When an agent works on a request, relevant conversation content, instructions and tool results may be sent to the configured model provider. Check the provider’s policies before sharing sensitive information.',
      ],
      [
        'Deployment-specific policies',
        'Retention, backups, hosting location and privacy requests depend on the operator of this installation. Contact your workspace administrator for the policy that applies to your data.',
      ],
    ],
  },
  terms: {
    title: 'Terms',
    intro: 'Using an Openlet workspace.',
    sections: [
      [
        'Your account',
        'Use an account you are authorised to access. Keep your sign-in codes private and let your workspace administrator know if you suspect unauthorised access.',
      ],
      [
        'Working with agents',
        'Agents can make mistakes. Review generated content and actions before relying on them. Only upload content and connect services you have permission to use.',
      ],
      [
        'Workspace access',
        'Workspace owners manage invitations, agent access and storage permissions. Access can change when membership or permissions change.',
      ],
      [
        'Service-specific terms',
        'Availability, billing, support and other contractual terms are set by the operator of this installation. Contact your workspace administrator for the terms that govern your workspace.',
      ],
    ],
  },
};
export function LegalPage({ kind }: { kind: keyof typeof content }) {
  const page = content[kind];
  usePageTitle(page.title);
  return (
    <PublicLayout>
      <main id="main-content" className={`${siteWidth} py-16 sm:py-24`}>
        <article className="mx-auto max-w-[700px]">
          <Link
            to="/"
            className="inline-flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="size-3" />
            Back to home
          </Link>
          <h1 className="mt-9 text-5xl font-medium tracking-[-0.04em] sm:text-6xl">{page.title}</h1>
          <p className="mt-6 text-xl leading-8 text-muted-foreground">{page.intro}</p>
          <div className="mt-12 space-y-10">
            {page.sections.map(([title, copy]) => (
              <section key={title}>
                <h2 className="text-xl font-medium tracking-[-0.02em]">{title}</h2>
                <p className="mt-3 text-[15px] leading-7 text-muted-foreground">{copy}</p>
              </section>
            ))}
          </div>
          <div className="mt-14 border-t border-border pt-6 text-sm">
            <Link
              to={kind === 'terms' ? '/privacy' : '/terms'}
              className="underline underline-offset-4"
            >
              {kind === 'terms' ? 'Privacy' : 'Terms'}
            </Link>
          </div>
        </article>
      </main>
    </PublicLayout>
  );
}
