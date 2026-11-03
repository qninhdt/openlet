package authz

import (
	"os"
	"regexp"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestParseRolePolicyRejectsInvalidCapabilities(t *testing.T) {
	for _, data := range []string{
		`null`, `{}`, `[]`,
		`{"owner":["node_read"],"editor":["node_read"]}`,
		`{"owner":["node_read"],"editor":["node_read"],"unknown":["node_read"]}`,
		`{"owner":["node_read"],"editor":[],"viewer":["node_read"]}`,
		`{"owner":["node_read"],"editor":["node_read","node_read"],"viewer":["node_read"]}`,
		`{"owner":["account_update"],"editor":["node_read"],"viewer":["node_read"]}`,
		`{"owner":["unknown"],"editor":["node_read"],"viewer":["node_read"]}`,
		`{"owner":["node_read"],"editor":["node_read"],"viewer":["node_read"]} {}`,
	} {
		_, err := ParseRolePolicy([]byte(data))
		require.ErrorIs(t, err, ErrInvalidPolicy, data)
	}
}

func TestRepositoryPolicyCoversDeclaredRoleActions(t *testing.T) {
	data, err := os.ReadFile("../../contracts/authz/roles.json")
	require.NoError(t, err)
	policy, err := ParseRolePolicy(data)
	require.NoError(t, err)
	schema, err := os.ReadFile("../../contracts/authz/schema.zed")
	require.NoError(t, err)
	role := strings.Split(strings.Split(string(schema), "definition role {")[1], "}")[0]
	var declared []string
	for _, match := range regexp.MustCompile(`relation (\w+): user:\*`).FindAllStringSubmatch(role, -1) {
		declared = append(declared, match[1])
	}
	var owner []string
	for _, relationship := range policy {
		if relationship.Resource.ObjectId == "owner" {
			owner = append(owner, relationship.Relation)
		}
		require.Contains(t, declared, relationship.Relation)
	}
	require.NotEmpty(t, declared)
	require.ElementsMatch(t, declared, owner, "Owner must cover every supported role action")
}
