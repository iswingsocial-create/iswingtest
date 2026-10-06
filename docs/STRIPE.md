# Connecter Stripe

Stripe n'est pas actif tant que les trois valeurs ci-dessous sont vides. Le bouton d'abonnement reste masqué.

Stripe indique qu'il ne prend pas en charge les services de rencontres à caractère sexuel, sauf accord explicite de leur part. Crée le compte en décrivant l'activité honnêtement. Si le compte est refusé, utilise CCBill, Segpay ou Epoch. Ne présente pas le paiement comme ouvert au public avant cet accord.

## Mode test

1. Crée un compte sur https://dashboard.stripe.com/register
2. Reste en mode Test (interrupteur en haut à droite).
3. Produits : crée « iSwing Premium », prix récurrent 29,99 USD par mois. Copie l'identifiant `price_...`.
4. Développeurs → Clés API : copie la clé secrète `sk_test_...` et la clé publique `pk_test_...`.
5. Développeurs → Webhooks → Ajouter un endpoint.
   - En local, Stripe ne joint pas `localhost`. Utilise l'outil Stripe CLI : `stripe listen --forward-to localhost:8000/paiements/webhook/`
   - En production : `https://ton-domaine/paiements/webhook/`
   - Événements : `checkout.session.completed`, `invoice.paid`, `invoice.payment_failed`, `customer.subscription.deleted`, `charge.refunded`
   - Copie le secret `whsec_...`
6. Ouvrez Gestion → Configuration → Paiements. C'est l'endroit prévu pour la clé.
   - Collez `sk_test_...` dans le champ **Clé API secrète de test**.
   - Collez `pk_test_...` dans **Clé publique de test**.
   - Collez `price_...` dans **Identifiant de prix, test**.
   - Collez `whsec_...` dans **Secret de webhook, test**.
   - Enregistrez, puis utilisez **Tester la connexion**. Ce bouton ne crée aucun paiement.
7. Le fichier `.env` (`STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID`) n'est utile que si vous ne remplissez pas cet écran. Un champ laissé vide sur l'écran conserve la clé déjà enregistrée. Ne relancez `Demarrer.bat` que si vous avez modifié `.env`.
8. Compte membre → Abonnement → le bouton Stripe apparaît seulement si la clé, le prix et le mode test sont enregistrés.
9. Carte de test : `4242 4242 4242 4242`, date future, CVC quelconque. Aucun vrai débit.
10. L'accès illimité ne s'active qu'après la notification signée. Un retour navigateur ne suffit pas.

Coller une clé ne rend pas les paiements actifs. Stripe doit avoir accepté le site. Les clés `sk_live_` sont pour plus tard, seulement après cet accord et un domaine HTTPS. CCBill, Segpay et Epoch ne sont pas implémentés.

iSwing ne stocke pas les numéros de carte. Ne mets pas ces clés dans un ZIP ni dans un dépôt public.

Le passage en clés `sk_live_` se fait seulement après l'accord de Stripe et un domaine HTTPS.
