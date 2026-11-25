import { useEffect, useRef, useState } from 'react';
import { Link, useLocation } from '@tanstack/react-router';
import { AuthenticateWithRedirectCallback, useAuth } from '@clerk/react';
import { useSignIn } from '@clerk/react/legacy';
import { ArrowLeft, LoaderCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { PublicBrand, PublicLayout, usePageTitle } from './public-layout';
import { AppLoading } from './page-state';
import { publishableKey, safeReturnTo } from '@/lib/auth-navigation';
import { devAuthEnabled, fetchDevAccounts, writeDevAccount, type DevAccount } from '@/lib/dev-auth';

function GoogleMark() {
  return (
    <svg aria-hidden="true" viewBox="0 0 48 48" className="size-5">
      <path
        fill="#4285f4"
        d="M43.6 24.5c0-1.4-.1-2.8-.4-4.1H24v7.9h11a9.5 9.5 0 0 1-4.1 6.2v5.1h6.6c3.9-3.6 6.1-8.8 6.1-15.1Z"
      />
      <path
        fill="#34a853"
        d="M24 44c5.5 0 10.1-1.8 13.5-4.9l-6.6-5.1c-1.8 1.2-4.2 2-6.9 2-5.3 0-9.8-3.6-11.4-8.5H5.8v5.3A20.4 20.4 0 0 0 24 44Z"
      />
      <path fill="#fbbc05" d="M12.6 27.5a12.2 12.2 0 0 1 0-7V15H5.8a20 20 0 0 0 0 18l6.8-5.5Z" />
      <path
        fill="#ea4335"
        d="M24 12c3 0 5.7 1 7.8 3l5.8-5.8A19.7 19.7 0 0 0 24 4 20.4 20.4 0 0 0 5.8 15l6.8 5.5C14.2 15.6 18.7 12 24 12Z"
      />
    </svg>
  );
}
export function LoginPage() {
  usePageTitle('Sign in');
  const returnTo = useLocation({
    select: (location) => safeReturnTo(new URLSearchParams(location.searchStr).get('returnTo')),
  });
  return (
    <PublicLayout chrome={false}>
      <main id="main-content" className="grid min-h-svh place-items-center px-6 py-12">
        <section className="w-full max-w-[360px] text-center">
          <div className="mb-10 flex justify-center">
            <PublicBrand large />
          </div>
          <h1 className="text-2xl font-semibold tracking-[-0.035em]">Sign in to Openlet</h1>
          <p className="mt-3 text-sm leading-6 text-muted-foreground">
            {devAuthEnabled
              ? 'Choose a seeded local development account.'
              : 'Continue with your Google account.'}
          </p>
          {devAuthEnabled ? (
            <DevQuickLogin />
          ) : publishableKey ? (
            <GoogleLogin returnTo={returnTo} />
          ) : (
            <UnavailableGoogleLogin />
          )}
          <p className="mt-6 text-xs leading-6 text-muted-foreground">
            By continuing, you agree to our{' '}
            <Link to="/terms" className="underline underline-offset-3">
              Terms
            </Link>{' '}
            and{' '}
            <Link to="/privacy" className="underline underline-offset-3">
              Privacy
            </Link>
            .
          </p>
          <Link
            to="/"
            className="mt-10 inline-flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="size-3" />
            Back to home
          </Link>
        </section>
      </main>
    </PublicLayout>
  );
}
function DevQuickLogin() {
  const [accounts, setAccounts] = useState<DevAccount[] | null>(null);
  useEffect(() => {
    void fetchDevAccounts().then(setAccounts);
  }, []);
  if (accounts === null) {
    return (
      <div className="mt-7 flex justify-center">
        <LoaderCircle className="size-5 animate-spin text-muted-foreground" />
      </div>
    );
  }
  if (accounts.length === 0) {
    return (
      <p role="alert" className="mt-6 text-sm leading-6 text-muted-foreground">
        No local dev accounts found. Start the local stack with{' '}
        <code className="font-mono text-foreground">make dev</code> and reload.
      </p>
    );
  }
  return (
    <div className="mt-7 flex flex-col gap-2.5">
      {accounts.map((account) => (
        <Button
          key={account.handle}
          variant="outline"
          className="h-12 w-full justify-between rounded-lg px-4"
          onClick={() => {
            writeDevAccount(account);
            window.location.replace('/app');
          }}
        >
          <span className="font-medium">{account.name}</span>
          <span className="text-xs text-muted-foreground">{account.handle}</span>
        </Button>
      ))}
    </div>
  );
}
function UnavailableGoogleLogin() {
  const [error, setError] = useState(false);
  return (
    <>
      <Button className="mt-7 h-12 w-full rounded-lg" onClick={() => setError(true)}>
        <GoogleMark />
        Continue with Google
      </Button>
      {error && (
        <p role="alert" className="mt-4 text-sm leading-6 text-destructive">
          Google sign-in is not configured on this installation. Contact the workspace
          administrator.
        </p>
      )}
    </>
  );
}
function GoogleLogin({ returnTo }: { returnTo: string }) {
  const { signIn, isLoaded } = useSignIn();
  const { isSignedIn } = useAuth();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const busy = useRef(false);
  useEffect(() => {
    if (isSignedIn) window.location.replace(returnTo);
  }, [isSignedIn, returnTo]);
  return (
    <>
      <Button
        className="mt-7 h-12 w-full rounded-lg"
        disabled={!isLoaded || pending || isSignedIn}
        onClick={async () => {
          if (!isLoaded || busy.current) return;
          busy.current = true;
          setPending(true);
          setError('');
          try {
            await signIn.authenticateWithRedirect({
              strategy: 'oauth_google',
              redirectUrl: `/sso-callback?returnTo=${encodeURIComponent(returnTo)}`,
              redirectUrlComplete: returnTo,
            });
          } catch (issue) {
            setError(
              issue instanceof Error
                ? issue.message
                : 'Google sign-in could not be started. Try again.',
            );
            busy.current = false;
            setPending(false);
          }
        }}
      >
        {pending ? <LoaderCircle className="size-4 animate-spin" /> : <GoogleMark />}
        {pending ? 'Connecting to Google…' : 'Continue with Google'}
      </Button>
      {error && (
        <p role="alert" className="mt-4 text-sm leading-6 text-destructive">
          {error}
        </p>
      )}
    </>
  );
}
export function SignInCallback() {
  const returnTo = useLocation({
    select: (location) => safeReturnTo(new URLSearchParams(location.searchStr).get('returnTo')),
  });
  if (!publishableKey) return <LoginPage />;
  return (
    <>
      <AppLoading label="Completing sign-in…" />
      <AuthenticateWithRedirectCallback
        signInForceRedirectUrl={returnTo}
        signUpForceRedirectUrl={returnTo}
      />
    </>
  );
}
