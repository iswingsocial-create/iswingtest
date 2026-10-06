# Connecter Stripe

Stripe n'est pas actif tant que les trois valeurs ci-dessous sont vides. Le bouton d'abonnement reste masqué.

Stripe indique qu'il ne prend pas en charge les services de rencontres à caractère sexuel, sauf accord explicite de leur part. Crée le compte en décrivant l'activité honnêtement. Si le compte est refusé, utilise CCBill, Segpay ou Epoch. Ne présente pas le paiement comme ouvert au public avant cet accord.

## Mode test

1. Crée un compte sur https://dashboard.stripe.com/register
2. Reste en mode Test (interrupteur en haut à droite).
3. Produits : crée « iSwing Premium », prix récurrent 29,99 USD par mois. Copie l'identifiant `price_...`.
4. Développeurs → Clés API : copie la clé secrète `sk_test_...`. Ne copie pas la clé publique dans iSwing.
5. Développeurs → Webhooks → Ajouter un endpoint.
   - En local, Stripe ne joint pas `localhost`. Utilise l'outil Stripe CLI : `stripe listen --forward-to localhost:8000/paiements/webhook/`
   - En production : `https://ton-domaine/paiements/webhook/`
   - Événements : `checkout.session.completed`, `invoice.paid`, `invoice.payment_failed`, `customer.subscription.deleted`, `charge.refunded`
   - Copie le secret `whsec_...`
6. Dans le fichier `.env` à côté de `manage.py` :

```
PAYMENT_PROVIDER=stripe
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_ID=price_...
ISWING_PUBLIC_BASE_URL=http://localhost:8000
```

7. Relance `Demarrer.bat`.
8. Compte membre → Abonnement → le bouton Stripe apparaît.
9. Carte de test : `4242 4242 4242 4242`, date future, CVC quelconque. Aucun vrai débit.
10. L'accès illimité ne s'active qu'après la notification signée. Un retour navigateur ne suffit pas.

iSwing ne stocke pas les numéros de carte. Ne mets pas ces clés dans un ZIP ni dans un dépôt public.

Le passage en clés `sk_live_` se fait seulement après l'accord de Stripe et un domaine HTTPS.
