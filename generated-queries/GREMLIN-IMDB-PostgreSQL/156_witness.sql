SET join_collapse_limit = 1;
SELECT count(*)
FROM (((title CROSS JOIN kind_type) CROSS JOIN cast_info) CROSS JOIN char_name) CROSS JOIN aka_title
WHERE char_name.surname_pcode = ''
  AND aka_title.kind_id = kind_type.id
  AND aka_title.movie_id = title.id
  AND cast_info.movie_id = title.id
  AND cast_info.person_role_id = char_name.id
  AND title.kind_id = kind_type.id;
